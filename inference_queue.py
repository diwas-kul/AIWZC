import queue
import threading
import logging
from pathlib import Path
import subprocess
import time
import os
from datetime import datetime
import json
import requests

logger = logging.getLogger(__name__)

class InferenceTask:
    """Represents a single inference task with detailed timing information."""
    def __init__(self, video_path, subject_id, session_id):
        self.video_path = video_path
        self.subject_id = subject_id
        self.session_id = session_id
        
        # Timing information
        self.recording_timestamp = self._get_recording_timestamp(video_path)
        self.queue_add_time = datetime.now()
        self.processing_start_time = None
        self.completion_time = None
        
        self.status = "queued"  # possible values: queued, processing, completed, failed
        self.error = None

    def _get_recording_timestamp(self, video_path):
        """Extract timestamp from video filename (format: recording_YYYYMMDD_HHMMSS.mp4)"""
        try:
            timestamp_str = video_path.split('_')[1:3]  # ['YYYYMMDD', 'HHMMSS.mp4']
            timestamp_str = '_'.join(timestamp_str).replace('.mp4', '')
            return datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
        except:
            return None

    def start_processing(self):
        """Mark task as started processing."""
        self.status = "processing"
        self.processing_start_time = datetime.now()

    def complete(self, status="completed", error=None):
        """Mark task as completed or failed."""
        self.status = status
        self.error = error
        self.completion_time = datetime.now()
        return self.get_log_entry()

    def get_status_info(self):
        """Get detailed status information including timing."""
        now = datetime.now()
        
        # Calculate time deltas
        time_since_recording = None
        if self.recording_timestamp:
            time_since_recording = (now - self.recording_timestamp).total_seconds()
        
        time_in_queue = (now - self.queue_add_time).total_seconds()
        
        processing_time = None
        if self.processing_start_time:
            processing_time = (now - self.processing_start_time).total_seconds()

        return {
            "status": self.status,
            "video_path": self.video_path,
            "subject_id": self.subject_id,
            "session_id": self.session_id,
            "timing": {
                "recording_timestamp": self.recording_timestamp.isoformat() if self.recording_timestamp else None,
                "queue_add_time": self.queue_add_time.isoformat(),
                "processing_start_time": self.processing_start_time.isoformat() if self.processing_start_time else None,
                "time_since_recording": time_since_recording,
                "time_in_queue": time_in_queue,
                "processing_time": processing_time
            },
            "error": self.error
        }

    def get_log_entry(self):
        """Generate a log entry for completed task."""
        return {
            "video_path": self.video_path,
            "subject_id": self.subject_id,
            "session_id": self.session_id,
            "recording_timestamp": self.recording_timestamp.isoformat() if self.recording_timestamp else None,
            "queue_add_time": self.queue_add_time.isoformat(),
            "processing_start_time": self.processing_start_time.isoformat() if self.processing_start_time else None,
            "completion_time": self.completion_time.isoformat() if self.completion_time else None,
            "status": self.status,
            "error": self.error
        }
    

class InferenceQueueManager:
    """Manages inference tasks with detailed status tracking."""
    
    def __init__(self, inference_script_path=None):
        """Initialize the inference queue manager.
        
        Args:
            inference_script_path (str, optional): Path to the inference script.
                                                 Defaults to /app/Inference/pilot.py
        """
        self.inference_script = Path(inference_script_path if inference_script_path 
                                   else "/app/Inference/pilot.py")
        
        if not self.inference_script.exists():
            raise FileNotFoundError(f"Inference script not found at {self.inference_script}")
        
        self.task_queue = queue.Queue()
        self.current_task = None
        self.processing_thread = None
        self._stop_requested = False
        
        # Set up logging for completed tasks
        self.log_dir = Path("/app/logs")
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / "inference_tasks.log"
        
        self._start_processing()

    def _start_processing(self):
        """Start the processing thread if not already running."""
        if not self.processing_thread or not self.processing_thread.is_alive():
            self.processing_thread = threading.Thread(
                target=self._process_queue,
                daemon=True
            )
            self.processing_thread.start()
            logger.info("Started inference processing thread")

    def _upload_outcomes_to_api(self, subject_id, session_id):
        """
        Upload the inference outcomes JSON file to the external API.
        
        Args:
            subject_id (str): Subject identifier
            session_id (str): Session identifier
            
        Returns:
            bool: True if upload was successful, False otherwise
        """
        try:
            # Construct the path to the outcomes file
            outcomes_file = f"/app/Inference/exercise_outcomes/{subject_id}_session{session_id}_outcomes.json"
            
            if not os.path.exists(outcomes_file):
                logger.error(f"Outcomes file not found: {outcomes_file}")
                return False
                
            # API configuration - update these when you have the full details
            api_url = "https://staging.data-api.moveup.care/srp_dump_json_file"
            api_key = "YOUR_API_KEY_HERE"  # Replace with your actual API key
            
            # Read the JSON file
            with open(outcomes_file, 'r') as f:
                json_data = json.load(f)
            
            # Prepare the request
            headers = {
                "Authorization": f"ApiKey {api_key}",
                "Content-Type": "application/json"
                # Add any other required headers when you get them
            }
            
            # Send the request
            logger.info(f"Uploading outcomes file to API: {outcomes_file}")
            response = requests.post(
                api_url,
                json=json_data,  # Send as JSON body
                headers=headers,
                timeout=30  # 30-second timeout
            )
            
            # Check if successful
            if response.status_code in (200, 201):
                logger.info(f"Successfully uploaded outcomes to API: {response.status_code}")
                return True
            else:
                logger.error(f"API upload failed with status code {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error uploading outcomes to API: {str(e)}")
            return False

    def _process_queue(self):
        """Process tasks from the queue sequentially."""
        while not self._stop_requested:
            try:
                task = self.task_queue.get(timeout=1)
                self.current_task = task
                task.start_processing()
                
                try:
                    logger.info(f"Starting inference for video: {task.video_path}")
                    os.chdir("/app/Inference")
                    
                    cmd = [
                        "python",
                        str(self.inference_script),
                        "--video", task.video_path,
                        "--subject_id", task.subject_id,
                        "--session_id", task.session_id
                    ]
                    
                    process = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    
                    log_entry = task.complete("completed")
                    logger.info(f"Completed inference for video: {task.video_path}")
                
                    api_upload_success = self._upload_outcomes_to_api(task.subject_id, task.session_id)
                    if api_upload_success:
                        logger.info(f"Successfully uploaded outcomes for subject {task.subject_id}, session {task.session_id}")
                    else:
                        logger.warning(f"Failed to upload outcomes for subject {task.subject_id}, session {task.session_id}")

                except subprocess.CalledProcessError as e:
                    log_entry = task.complete("failed", str(e.stderr))
                    logger.error(f"Error running inference: {e.stderr}")
                    
                except Exception as e:
                    log_entry = task.complete("failed", str(e))
                    logger.error(f"Unexpected error during inference: {str(e)}")
                    
                finally:
                    self._log_completed_task(log_entry)
                    self.current_task = None
                    self.task_queue.task_done()
                    
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in queue processing: {str(e)}")
                time.sleep(1)

    def _log_completed_task(self, task_info):
        """Log completed task information to file."""
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(task_info) + '\n')
        except Exception as e:
            logger.error(f"Error logging task completion: {str(e)}")

    def add_task(self, video_path, subject_id, session_id):
        """Add a new inference task to the queue."""
        task = InferenceTask(video_path, subject_id, session_id)
        self.task_queue.put(task)
        logger.info(f"Added inference task for video: {video_path}")
        return task

    def get_queue_status(self):
        """Get comprehensive status of current and pending tasks."""
        # Get list of pending tasks
        pending_tasks = list(self.task_queue.queue)
        
        queue_info = {
            "queue_length": len(pending_tasks),
            "current_task": self.current_task.get_status_info() if self.current_task else None,
            "pending_tasks": [task.get_status_info() for task in pending_tasks]
        }
        
        # Add human-readable summary
        summary = []
        if self.current_task:
            current_info = queue_info["current_task"]
            processing_time = current_info["timing"]["processing_time"]
            processing_str = f"{processing_time:.1f}s" if processing_time else "starting..."
            
            summary.append(
                f"Currently processing: {os.path.basename(current_info['video_path'])} "
                f"(processing for {processing_str})"
            )
        
        if pending_tasks:
            summary.append(f"Pending tasks: {len(pending_tasks)}")
            for task in pending_tasks:
                task_info = task.get_status_info()
                time_in_queue = task_info["timing"]["time_in_queue"]
                summary.append(
                    f"  - {os.path.basename(task_info['video_path'])} "
                    f"(Subject {task_info['subject_id']}, Session {task_info['session_id']}, "
                    f"waiting for {time_in_queue:.1f}s)"
                )
        
        queue_info["summary"] = summary
        return queue_info

    def stop(self):
        """Stop the queue processing thread gracefully."""
        self._stop_requested = True
        if self.processing_thread:
            self.processing_thread.join(timeout=5)
            logger.info("Stopped inference processing thread")