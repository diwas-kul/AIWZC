from flask import Flask, jsonify, request
import subprocess
import threading
import logging
import functools
from datetime import datetime, timedelta
from pathlib import Path
import jwt
import time
import socket
import requests

from inference_queue import InferenceQueueManager
inference_queue = InferenceQueueManager("/app/Inference/pilot.py")

app = Flask(__name__)
# WARNING: Change this in production!
app.config['SECRET_KEY'] = 'AI@WZCProject'
app.config['JWT_EXPIRATION_HOURS'] = 168  # 1 week expiration
app.config['UPLOAD_TIMEOUT'] = 300  # 5 minutes timeout for ManGO uploads

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def require_auth(f):
    """Decorator to require JWT authentication for routes."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'message': 'Missing authorization header'}), 401
        
        try:
            token = auth_header.split(' ')[1]
            jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid token'}), 401
        except Exception as e:
            return jsonify({'message': f'Authentication error: {str(e)}'}), 401
            
        return f(*args, **kwargs)
    return decorated

class RecordingManager:
    """Manages RTSP recording sessions and ManGO uploads."""
    
    def __init__(self, rtsp_url, subject_id="subject3", session_id="0", 
                 duration=120, irods_path="/set/home/Gait_Team/AI@WZC/VideoUpload"):
        """
        Initialize the recording manager.
        
        Args:
            rtsp_url (str): RTSP stream URL
            subject_id (str): Subject identifier
            session_id (str): Session identifier
            duration (int): Maximum recording duration in seconds
            irods_path (str): ManGO upload destination path
        """
        self.rtsp_url = rtsp_url
        self.subject_id = subject_id
        self.session_id = session_id
        self.duration = duration
        self.irods_path = irods_path
        self.is_recording = False
        self.output_dir = Path("/recordings")
        self.output_dir.mkdir(exist_ok=True)
        self.process = None
        self._upload_thread = None
        self._recording_start_time = None
        self.current_task_id = None

    def start_recording(self):
        """Start a new recording session."""
        if self.is_recording:
            return False, "Already recording"

        try:
            cmd = [
                "python", 
                "/app/rtsp_recorder.py",
                self.rtsp_url,
                "-d", str(self.duration),
                "-o", str(self.output_dir),
                # "--delay", "0"  # Add 10 second delay
            ]
            
            logger.info(f"Starting recording with command: {' '.join(cmd)}")
            self.process = subprocess.Popen(cmd)
            self.is_recording = True
            self._recording_start_time = time.time()
            
            self._upload_thread = threading.Thread(
                target=self._handle_recording_completion,
                daemon=True
            )
            self._upload_thread.start()
            
            return True, "Recording started"
            
        except Exception as e:
            logger.error(f"Error starting recording: {str(e)}")
            return False, str(e)

    def stop_recording(self):
        """
        Stop the current recording gracefully.
        Ensures the video is properly saved and uploaded to ManGO.
        """
        if not self.is_recording:
            return False, "No active recording"

        try:
            if self.process:
                # Calculate elapsed time
                elapsed_time = time.time() - self._recording_start_time
                logger.info(f"Stopping recording after {elapsed_time:.2f} seconds")
                
                # Send terminate signal and wait for completion
                self.process.terminate()
                try:
                    # Wait with timeout to avoid hanging
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("Process termination timed out, forcing kill")
                    self.process.kill()
                    self.process.wait()
                
                # At this point, the recording should be saved
                # Now we need to manually trigger the upload since the normal completion thread
                # might not run properly due to the early termination
                
                try:
                    latest_recording = max(
                        self.output_dir.glob("recording_*.mp4"),
                        key=lambda p: p.stat().st_mtime,
                        default=None
                    )
                    
                    if latest_recording is None:
                        logger.error("No recording file found after stopping")
                        return False, "Recording stopped but no file was found"
                    
                    # Check if file is valid (not empty and properly finalized)
                    if latest_recording.stat().st_size == 0:
                        logger.error("Recording file is empty")
                        return False, "Recording stopped but file is empty"
                    
                    # Wait a moment to make sure the file is properly closed
                    time.sleep(1)
                    
                    # Upload to ManGO
                    logger.info(f"Uploading stopped recording {latest_recording} to ManGO at {self.irods_path}")
                    upload_cmd = ["iput", str(latest_recording), self.irods_path]
                    
                    upload_process = subprocess.run(
                        upload_cmd,
                        capture_output=True,
                        text=True,
                        timeout=app.config['UPLOAD_TIMEOUT']
                    )
                    
                    if upload_process.returncode == 0:
                        logger.info("Upload of stopped recording successful")

                        # Queue inference task
                        self.current_task_id = inference_queue.add_task(
                            str(latest_recording),
                            self.subject_id,
                            self.session_id
                        )
                        logger.info(f"Queued inference task with ID: {self.current_task_id} for stopped recording")
                        
                        # Reset recording state
                        self.is_recording = False
                        self.process = None
                        self._recording_start_time = None
                        
                        return True, "Recording stopped, saved, and uploaded successfully"
                    else:
                        error_msg = f"Upload to ManGO failed: {upload_process.stderr}"
                        logger.error(error_msg)
                        return False, error_msg
                        
                except Exception as e:
                    error_msg = f"Error processing stopped recording: {str(e)}"
                    logger.error(error_msg)
                    return False, error_msg
                    
            return False, "No active recording process to stop"
        except Exception as e:
            logger.error(f"Error stopping recording: {str(e)}")
            # Make sure to reset the recording state even if there's an error
            self.is_recording = False
            self.process = None
            self._recording_start_time = None
            return False, str(e)

    def _handle_recording_completion(self):
        """Handle the recording completion and ManGO upload process."""
        try:
            # Wait for recording to complete
            self.process.wait()
            
            # Check if we've already processed this recording (could happen if stop_recording was called)
            if not self.is_recording:
                logger.info("Recording already processed, skipping duplicate processing")
                return
                
            if self.process.returncode == 0:
                try:
                    latest_recording = max(
                        self.output_dir.glob("recording_*.mp4"),
                        key=lambda p: p.stat().st_mtime,
                        default=None
                    )
                    
                    if latest_recording is None:
                        logger.error("No recording file found")
                        return
                    
                    # Upload to ManGO
                    logger.info(f"Uploading {latest_recording} to ManGO at {self.irods_path}")
                    upload_cmd = ["iput", str(latest_recording), self.irods_path]
                    
                    upload_process = subprocess.run(
                        upload_cmd,
                        capture_output=True,
                        text=True,
                        timeout=app.config['UPLOAD_TIMEOUT']
                    )
                    
                    if upload_process.returncode == 0:
                        logger.info("Upload successful")


                        # Queue inference task
                        self.current_task_id = inference_queue.add_task(
                            str(latest_recording),
                            self.subject_id,
                            self.session_id
                        )
                        logger.info(f"Queued inference task with ID: {self.current_task_id}")

                    else:
                        logger.error(f"Upload to ManGO failed: {upload_process.stderr}")
                except subprocess.TimeoutExpired:
                    logger.error("Upload timeout exceeded")
                except Exception as e:
                    logger.error(f"Error during file upload: {str(e)}")
            else:
                logger.error("Recording process failed")
                
        except Exception as e:
            logger.error(f"Error in recording completion handler: {str(e)}")
        finally:
            self.is_recording = False
            self.process = None
            self._recording_start_time = None


    def get_inference_status(self):
        """Get the status of the current inference task if any."""
        if self.current_task_id:
            return inference_queue.get_task_status(self.current_task_id)
        return None

# Global recording manager instance
recording_manager = None

@app.route('/login', methods=['POST'])
def login():
    """Authenticate user and return JWT token."""
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        return jsonify({'message': 'Missing credentials'}), 401
    
    if auth.username == "admin" and auth.password == "AI@WZCProject":
        token = jwt.encode(
            {
                'user': auth.username,
                'exp': datetime.utcnow() + timedelta(hours=app.config['JWT_EXPIRATION_HOURS'])
            },
            app.config['SECRET_KEY']
        )
        return jsonify({'token': token})
    
    return jsonify({'message': 'Invalid credentials'}), 401


@app.route('/start_recording', methods=['POST'])
@require_auth
def start_recording_session():
    """Initialize recording manager and start recording in a single step."""
    global recording_manager
    try:
        # Get parameters from request body
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Missing request body"
            }), 400
            
        rtsp_url = data.get('rtsp_url')
        if not rtsp_url:
            return jsonify({
                "status": "error",
                "message": "Missing rtsp_url in request body"
            }), 400
            
        subject_id = data.get('subject_id', 'subject3')
        session_id = data.get('session_id', '0')
        
        # if not rtsp_url.startswith('rtsp://'):
            # rtsp_url = f"rtsp://{rtsp_url}"
            
        # Initialize recording manager
        recording_manager = RecordingManager(rtsp_url, subject_id=subject_id, session_id=session_id)
        logger.info(f"Initialized recording manager with URL: {rtsp_url}, subject_id: {subject_id}, session_id: {session_id}")
        
        # Start recording immediately
        success, message = recording_manager.start_recording()
        
        if not success:
            return jsonify({
                "status": "error",
                "message": f"Failed to start recording: {message}"
            }), 400
            
        return jsonify({
            "status": "success",
            "message": "Recording manager initialized and recording started",
            "rtsp_url": rtsp_url,
            "subject_id": subject_id,
            "session_id": session_id
        })
    except Exception as e:
        logger.error(f"Initialization and recording error: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
    

@app.route('/stop', methods=['POST'])
@require_auth
def stop_recording():
    """Stop current recording and trigger ManGO upload."""
    if not recording_manager:
        return jsonify({
            "status": "error",
            "message": "Recording manager not initialized"
        }), 400

    success, message = recording_manager.stop_recording()
    return jsonify({
        "status": "success" if success else "error",
        "message": message
    }), 200 if success else 400


@app.route('/status', methods=['GET'])
@require_auth
def get_status():
    """Get comprehensive status of both recording and inference queue."""
    if not recording_manager:
        return jsonify({
            "status": "error",
            "message": "Recording manager not initialized"
        }), 400

    # Get recording status
    recording_status = {
        "is_recording": recording_manager.is_recording,
        "recording_time": None
    }
    
    if recording_manager._recording_start_time:
        recording_status["recording_time"] = time.time() - recording_manager._recording_start_time
        
    # Get queue status from inference queue manager
    queue_status = inference_queue.get_queue_status()
    
    return jsonify({
        "status": "success",
        "recording": recording_status,
        "inference": {
            "current_task": queue_status["current_task"],
            "queue_length": queue_status["queue_length"],
            "pending_tasks": queue_status["pending_tasks"]
        }
    })

@app.route('/inference_status', methods=['GET'])
@require_auth
def get_inference_status():
    """Get detailed status of the inference queue."""
    if not recording_manager:
        return jsonify({
            "status": "error",
            "message": "Recording manager not initialized"
        }), 400
    
    # Get complete queue status
    queue_status = inference_queue.get_queue_status()
    
    # Add log file location for completed tasks
    queue_status["completed_tasks_log"] = str(inference_queue.log_file)
    
    return jsonify({
        "status": "success",
        "queue": queue_status
    })


# Add these functions near the start of the file
def get_vpn_ip():
    """Get the VPN IP address of this machine."""
    try:
        # Try to get the VPN IP by connecting to the VPN server
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.8.0.1", 51820))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        logger.warning("Could not determine VPN IP address")
        return None

def check_vpn_connection():
    """Check if the VPN connection is active."""
    try:
        # Try to ping the server over VPN
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("10.8.0.1", 51820))
        s.close()
        return True
    except:
        return False

# Add this near the end of the file, before app.run()
if __name__ == '__main__':
    # Make sure the recordings directory exists
    Path("/recordings").mkdir(exist_ok=True)
    
    # Check VPN connection
    vpn_connected = check_vpn_connection()
    vpn_ip = get_vpn_ip()
    
    logger.info(f"VPN Connection Status: {'Connected' if vpn_connected else 'Disconnected'}")
    if vpn_connected and vpn_ip:
        logger.info(f"VPN IP Address: {vpn_ip}")
    
    # WARNING: In production, use proper SSL certificates
    app.run(host='0.0.0.0', port=5000, ssl_context='adhoc')