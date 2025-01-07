import cv2
import time
import argparse
from datetime import datetime
import sys
from pathlib import Path

class RTSPRecorder:
    def __init__(self, rtsp_url, output_dir="recordings"):
        """Initialize the RTSP recorder"""
        self.rtsp_url = rtsp_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Initialize video capture
        self.cap = cv2.VideoCapture(rtsp_url)
        if not self.cap.isOpened():
            raise ConnectionError(f"Failed to connect to RTSP stream: {rtsp_url}")
        
        # Get video properties
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = int(self.cap.get(cv2.CAP_PROP_FPS))
        
        print(f"Connected to stream: {self.frame_width}x{self.frame_height} @ {self.fps}fps")

    def record(self, duration=120, stop_key='q'):
        """
        Record video for specified duration
        
        Args:
            duration (int): Recording duration in seconds
        """
        # Generate output filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"recording_{timestamp}.mp4"
        
        # Initialize video writer
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(
            str(output_path),
            fourcc,
            self.fps,
            (self.frame_width, self.frame_height)
        )
        
        start_time = time.time()
        frames_recorded = 0
        
        print(f"Recording to: {output_path}")
        
        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    print("Failed to read frame from stream")
                    break
                
                # Write frame
                out.write(frame)
                frames_recorded += 1
                
                # Check for stop conditions
                elapsed_time = time.time() - start_time
                if elapsed_time >= duration:
                    break
                
                # Show progress
                sys.stdout.write(f"\rRecording: {int(elapsed_time)}s / {duration}s")
                sys.stdout.flush()
        
        finally:
            # Clean up
            out.release()
            print(f"\nRecording stopped after {int(elapsed_time)} seconds")
            print(f"Recorded {frames_recorded} frames")
            print(f"Saved to: {output_path}")

    def __del__(self):
        """Cleanup when object is destroyed"""
        if hasattr(self, 'cap'):
            self.cap.release()

def main():
    parser = argparse.ArgumentParser(description='Record from RTSP stream')
    parser.add_argument('url', help='RTSP stream URL')
    parser.add_argument('-d', '--duration', type=int, default=120,
                       help='Recording duration in seconds (default: 120)')
    parser.add_argument('-o', '--output', default='recordings',
                       help='Output directory (default: recordings)')
    
    args = parser.parse_args()
    
    try:
        recorder = RTSPRecorder(args.url, args.output)
        recorder.record(args.duration)
    except KeyboardInterrupt:
        print("\nRecording interrupted by user")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()