import time
import argparse
import subprocess
from datetime import datetime
import sys
import logging
from pathlib import Path
import signal
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RTSPRecorder:
    """
    Class to handle RTSP stream recording with proper error handling and graceful shutdown.
    Uses ffmpeg directly for more reliable RTSP handling.
    """
    def __init__(self, rtsp_url, output_dir="recordings", reconnect_attempts=3):
        """
        Initialize the RTSP recorder.
        
        Args:
            rtsp_url (str): URL of the RTSP stream
            output_dir (str): Directory to save recordings
            reconnect_attempts (int): Number of times to attempt reconnection
        """
        self.rtsp_url = rtsp_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.reconnect_attempts = reconnect_attempts
        self.stop_recording = False
        self.current_output_path = None
        self.process = None
        
        # Stream properties - can be adjusted as needed
        self.frame_width = 1280  # Default, will be updated if possible
        self.frame_height = 720  # Default, will be updated if possible
        self.fps = 24           # Using 24 fps as default
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Initialize by probing the stream
        # self._probe_stream() # Removed probing to prevent delay
 
    def _probe_stream(self):
        """Probe the stream to get information about it."""
        try:
            # Use ffprobe to get stream information
            cmd = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate",
                "-of", "csv=p=0",
                self.rtsp_url
            ]
            
            logger.info(f"Probing stream with command: {' '.join(cmd)}")
            
            for attempt in range(self.reconnect_attempts):
                try:
                    # Set a timeout to avoid hanging forever
                    result = subprocess.run(
                        cmd, 
                        capture_output=True, 
                        text=True, 
                        timeout=30
                    )
                    
                    if result.returncode == 0 and result.stdout.strip():
                        # Parse output: width,height,frame_rate
                        parts = result.stdout.strip().split(',')
                        if len(parts) >= 3:
                            self.frame_width = int(parts[0])
                            self.frame_height = int(parts[1])
                            
                            # Parse frame rate which might be in the form "num/denom"
                            fps_parts = parts[2].split('/')
                            if len(fps_parts) == 2 and int(fps_parts[1]) > 0:
                                self.fps = int(float(fps_parts[0]) / float(fps_parts[1]))
                            elif len(fps_parts) == 1:
                                self.fps = int(float(fps_parts[0]))
                            
                            # Validate and cap unrealistic values
                            if self.fps <= 0 or self.fps > 60:
                                self.fps = 24  # Default to 24 if unrealistic
                            
                            logger.info(f"Stream information: {self.frame_width}x{self.frame_height} @ {self.fps}fps")
                            return
                        
                    logger.warning(f"Could not parse stream info on attempt {attempt+1}: {result.stdout}")
                    
                except subprocess.TimeoutExpired:
                    logger.error(f"Timeout while probing stream on attempt {attempt+1}")
                    
                except Exception as e:
                    logger.error(f"Error probing stream on attempt {attempt+1}: {str(e)}")
                
                if attempt < self.reconnect_attempts - 1:
                    logger.info(f"Retrying stream probe in 2 seconds...")
                    time.sleep(2)
            
            # If we reached here, use default values
            logger.warning("Could not determine stream properties, using defaults")
                
        except Exception as e:
            logger.error(f"Failed to probe stream: {str(e)}")
            logger.warning("Using default stream properties")
        
    def _handle_signal(self, signum, frame):
        """Handle termination signals gracefully."""
        logger.info(f"Received signal {signum}, stopping recording gracefully...")
        self.stop_recording = True
        if self.process:
            self._terminate_ffmpeg()

    def _terminate_ffmpeg(self):
        """Terminate ffmpeg process gracefully."""
        if self.process:
            try:
                logger.info("Terminating ffmpeg process...")
                
                # First try sending 'q' to ffmpeg for clean exit
                if self.process.poll() is None:  # if process is still running
                    try:
                        if hasattr(self.process, 'stdin') and self.process.stdin:
                            self.process.stdin.write(b'q')
                            self.process.stdin.flush()
                            
                        # Give it a moment to terminate
                        for _ in range(5):
                            if self.process.poll() is not None:
                                break
                            time.sleep(0.1)
                    except:
                        pass
                
                # If still running, terminate more forcefully
                if self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=5)
                
                logger.info("FFmpeg process terminated")
            except Exception as e:
                logger.error(f"Error terminating process: {str(e)}")
                # Kill forcefully as last resort
                try:
                    if self.process.poll() is None:
                        self.process.kill()
                except:
                    pass

    def record(self, duration=120, delay=0):
        """
        Record video for specified duration using ffmpeg.
        
        Args:
            duration (int): Recording duration in seconds
            delay (int): Delay in seconds before starting the recording
                
        Returns:
            bool: True if recording completed successfully, False otherwise
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_output_path = self.output_dir / f"recording_{timestamp}.mp4"
        
        # Add delay before starting recording
        if delay > 0:
            logger.info(f"Delaying recording start for {delay} seconds...")
            for remaining in range(delay, 0, -1):
                if self.stop_recording:
                    logger.info("Recording delay interrupted")
                    return False
                logger.info(f"Recording will start in {remaining} seconds...")
                time.sleep(1)
            logger.info("Starting recording now!")
        
        # Prepare ffmpeg command
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output files without asking
            "-rtsp_transport", "tcp",  # Use TCP for more reliable transport
            "-i", self.rtsp_url,
            "-t", str(duration),  # Duration in seconds
            "-c:v", "libx264",    # Use H.264 encoding
            "-preset", "ultrafast", # Fast encoding
            "-r", str(self.fps),   # Force output framerate
            "-vsync", "vfr",      # Variable framerate to handle timing issues
            "-an",                # No audio (remove if you want audio)
            str(self.current_output_path)
        ]
        
        logger.info(f"Starting recording with command: {' '.join(cmd)}")
        start_time = time.time()
        
        try:
            # Start ffmpeg process
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Create a monitoring thread to track progress and check for errors
            self.stop_recording = False
            monitoring_thread = threading.Thread(
                target=self._monitor_recording,
                args=(start_time, duration),
                daemon=True
            )
            monitoring_thread.start()
            
            # Wait for the ffmpeg process to complete
            stdout, stderr = self.process.communicate()
            end_time = time.time()
            elapsed_time = end_time - start_time
            return_code = self.process.returncode
            
            # Process output
            if return_code != 0:
                logger.error(f"FFmpeg error (return code {return_code}): {stderr.decode('utf-8', errors='ignore')}")
                return False
            
            # Log completion
            logger.info(f"Recording finished after {int(elapsed_time)} seconds")
            logger.info(f"Saved to: {self.current_output_path}")
            
            # Verify the output file
            if self.current_output_path.exists() and self.current_output_path.stat().st_size > 0:
                logger.info("Recording saved successfully")
                # Get video duration
                self._get_video_info()
                return True
            else:
                logger.error("Recording file is empty or missing")
                return False
            
        except Exception as e:
            logger.error(f"Error during recording: {str(e)}")
            if self.process and self.process.poll() is None:
                self._terminate_ffmpeg()
            return False

    def _monitor_recording(self, start_time, duration):
        """Thread function to monitor recording progress and handle early termination."""
        try:
            # Check progress periodically
            while not self.stop_recording:
                current_time = time.time()
                elapsed_time = current_time - start_time
                
                # Exit if duration reached or process completed
                if elapsed_time >= duration or (self.process and self.process.poll() is not None):
                    break
                
                # Show progress
                progress = (elapsed_time / duration) * 100
                logger.info(f"Recording progress: {progress:.1f}% ({int(elapsed_time)}s/{duration}s)")
                
                # Sleep before next check
                time.sleep(max(1, min(5, duration / 20)))  # Dynamic sleep interval
            
            # Check if we need to terminate early
            if self.stop_recording and self.process and self.process.poll() is None:
                logger.info("Stopping recording early...")
                self._terminate_ffmpeg()
                
        except Exception as e:
            logger.error(f"Error in monitoring thread: {str(e)}")
    
    def _get_video_info(self):
        """Get information about the recorded video."""
        try:
            if not self.current_output_path or not self.current_output_path.exists():
                return
                
            cmd = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration,r_frame_rate",
                "-of", "csv=p=0",
                str(self.current_output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(',')
                if len(parts) >= 4:
                    width = parts[0]
                    height = parts[1]
                    duration = float(parts[2]) if parts[2] != "N/A" else "unknown"
                    fps_parts = parts[3].split('/')
                    fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else parts[3]
                    
                    logger.info(f"Recorded video: {width}x{height}, {duration}s, {fps}fps")
                    
        except Exception as e:
            logger.error(f"Error getting video info: {str(e)}")

    def __del__(self):
        """Cleanup when object is destroyed."""
        if hasattr(self, 'process') and self.process and self.process.poll() is None:
            self._terminate_ffmpeg()


def main():
    """Main function to handle command-line interface."""
    parser = argparse.ArgumentParser(description='Record from RTSP stream')
    parser.add_argument('url', help='RTSP stream URL')
    parser.add_argument('-d', '--duration', type=int, default=120,
                       help='Recording duration in seconds (default: 120)')
    parser.add_argument('-o', '--output', default='recordings',
                       help='Output directory (default: recordings)')
    parser.add_argument('-r', '--retry', type=int, default=3,
                       help='Number of reconnection attempts (default: 3)')
    parser.add_argument('--delay', type=int, default=0,
                       help='Delay in seconds before starting the recording (default: 0)')

    args = parser.parse_args()
    
    try:
        recorder = RTSPRecorder(args.url, args.output, args.retry)
        if not recorder.record(args.duration, args.delay):
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\nRecording interrupted by user")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()