import cv2
import time
import argparse
from datetime import datetime
import sys
import logging
from pathlib import Path
import signal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RTSPRecorder:
    """
    Class to handle RTSP stream recording with proper error handling and graceful shutdown.
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
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        
        # Initialize video capture
        self._initialize_capture()

    def _initialize_capture(self):
        """Initialize video capture with retry mechanism."""
        for attempt in range(self.reconnect_attempts):
            try:
                self.cap = cv2.VideoCapture(self.rtsp_url)
                if not self.cap.isOpened():
                    raise ConnectionError(f"Failed to connect to RTSP stream")
                
                # Get video properties
                self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.fps = int(self.cap.get(cv2.CAP_PROP_FPS))
                
                if self.fps <= 0:
                    self.fps = 30  # Fallback to default FPS if not detected
                
                if self.frame_width <= 0 or self.frame_height <= 0:
                    raise ValueError("Invalid frame dimensions")
                
                logger.info(f"Connected to stream: {self.frame_width}x{self.frame_height} @ {self.fps}fps")
                return
                
            except Exception as e:
                logger.error(f"Attempt {attempt + 1}/{self.reconnect_attempts} failed: {str(e)}")
                if hasattr(self, 'cap') and self.cap:
                    self.cap.release()
                if attempt < self.reconnect_attempts - 1:
                    time.sleep(2)  # Wait before retrying
                else:
                    raise ConnectionError(f"Failed to connect to RTSP stream after {self.reconnect_attempts} attempts")

    def _handle_signal(self, signum, frame):
        """Handle termination signals gracefully."""
        logger.info(f"Received signal {signum}, stopping recording gracefully...")
        self.stop_recording = True

    def record(self, duration=120):
        """
        Record video for specified duration with error handling and progress tracking.
        
        Args:
            duration (int): Recording duration in seconds
            
        Returns:
            bool: True if recording completed successfully, False otherwise
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_output_path = self.output_dir / f"recording_{timestamp}.mp4"
        
        # Initialize video writer with error handling
        try:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(
                str(self.current_output_path),
                fourcc,
                self.fps,
                (self.frame_width, self.frame_height)
            )
            
            if not out.isOpened():
                raise IOError("Failed to create video writer")
            
        except Exception as e:
            logger.error(f"Failed to initialize video writer: {str(e)}")
            if hasattr(self, 'cap'):
                self.cap.release()
            raise

        logger.info(f"Recording to: {self.current_output_path}")
        start_time = time.time()
        frames_recorded = 0
        last_frame_time = start_time
        reconnection_count = 0
        max_reconnections = 3
        
        try:
            while not self.stop_recording:
                ret, frame = self.cap.read()
                current_time = time.time()
                elapsed_time = current_time - start_time
                
                if elapsed_time >= duration:
                    logger.info("Recording duration reached")
                    break
                
                if not ret:
                    frame_delay = current_time - last_frame_time
                    if frame_delay > 5.0:  # No frame for 5 seconds
                        logger.warning("No frames received for 5 seconds")
                        if reconnection_count < max_reconnections:
                            logger.info("Attempting stream reconnection...")
                            self.cap.release()
                            self._initialize_capture()
                            reconnection_count += 1
                            last_frame_time = time.time()
                            continue
                        else:
                            logger.error("Maximum reconnection attempts reached")
                            break
                else:
                    last_frame_time = current_time
                    out.write(frame)
                    frames_recorded += 1
                    reconnection_count = 0  # Reset counter on successful frame
                
                # Show progress every second
                if frames_recorded % self.fps == 0:
                    progress = (elapsed_time / duration) * 100
                    logger.info(f"Recording progress: {progress:.1f}% ({int(elapsed_time)}s/{duration}s)")
        
        except Exception as e:
            logger.error(f"Error during recording: {str(e)}")
            return False
        
        finally:
            # Cleanup
            out.release()
            self.cap.release()
            
            # Log recording statistics
            elapsed_time = time.time() - start_time
            logger.info(f"Recording finished after {int(elapsed_time)} seconds")
            logger.info(f"Recorded {frames_recorded} frames ({frames_recorded/elapsed_time:.1f} fps)")
            logger.info(f"Saved to: {self.current_output_path}")
            
            # Verify the output file
            if self.current_output_path.exists() and self.current_output_path.stat().st_size > 0:
                logger.info("Recording saved successfully")
                return True
            else:
                logger.error("Recording file is empty or missing")
                return False

    def __del__(self):
        """Cleanup when object is destroyed"""
        if hasattr(self, 'cap') and self.cap:
            self.cap.release()

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
    
    args = parser.parse_args()
    
    try:
        recorder = RTSPRecorder(args.url, args.output, args.retry)
        if not recorder.record(args.duration):
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\nRecording interrupted by user")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()