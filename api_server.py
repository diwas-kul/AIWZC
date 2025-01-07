from flask import Flask, jsonify
import subprocess
import threading
import logging
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RecordingManager:
    def __init__(self, rtsp_url, duration=180, irods_path="/set/home/Gait_Team/AI@WZC/VideoUpload"):
        self.rtsp_url = rtsp_url
        self.duration = duration
        self.irods_path = irods_path
        self.is_recording = False
        self.output_dir = Path("/recordings")
        self.output_dir.mkdir(exist_ok=True)

    def start_recording(self):
        if self.is_recording:
            return False, "Already recording"

        try:
            # Start recording script as a subprocess
            cmd = [
                "python", 
                "/app/rtsp_recorder.py",
                self.rtsp_url,
                "-d", str(self.duration),
                "-o", str(self.output_dir)
            ]
            
            logger.info(f"Starting recording with command: {' '.join(cmd)}")
            self.process = subprocess.Popen(cmd)
            self.is_recording = True
            
            # Start a thread to handle upload after recording
            threading.Thread(target=self._handle_recording_completion).start()
            
            return True, "Recording started"
            
        except Exception as e:
            logger.error(f"Error starting recording: {str(e)}")
            return False, str(e)

    def _handle_recording_completion(self):
        try:
            # Wait for recording to complete
            self.process.wait()
            
            if self.process.returncode == 0:
                # Find the latest recording
                latest_recording = max(
                    self.output_dir.glob("recording_*.mp4"),
                    key=lambda p: p.stat().st_mtime
                )
                
                # Upload using iput command
                logger.info(f"Uploading {latest_recording} to ManGO at {self.irods_path}")
                upload_cmd = ["iput", str(latest_recording), self.irods_path]
                
                upload_process = subprocess.run(
                    upload_cmd,
                    capture_output=True,
                    text=True
                )
                
                if upload_process.returncode == 0:
                    logger.info("Upload successful")
                    # Clean up local file
                    latest_recording.unlink()
                    logger.info(f"Removed local file: {latest_recording}")
                else:
                    logger.error(f"Upload failed: {upload_process.stderr}")
            else:
                logger.error("Recording process failed")
                
        except Exception as e:
            logger.error(f"Error in recording completion handler: {str(e)}")
        finally:
            self.is_recording = False

# Global recording manager instance
recording_manager = None

@app.route('/init/<path:rtsp_url>', methods=['POST'])
def initialize(rtsp_url):
    """
    Initialize with RTSP URL
    Example: /init/192.168.1.100:8554/stream
    """
    global recording_manager
    try:
        # Make sure the URL starts with rtsp://
        if not rtsp_url.startswith('rtsp://'):
            rtsp_url = f"rtsp://{rtsp_url}"
            
        recording_manager = RecordingManager(rtsp_url)
        logger.info(f"Initialized recording manager with URL: {rtsp_url}")
        
        return jsonify({
            "status": "success",
            "message": "Recording manager initialized",
            "rtsp_url": rtsp_url
        })
    except Exception as e:
        logger.error(f"Initialization error: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/start', methods=['POST'])
def start_recording():
    if not recording_manager:
        return jsonify({
            "status": "error",
            "message": "Recording manager not initialized. Call /init first."
        }), 400

    success, message = recording_manager.start_recording()
    return jsonify({
        "status": "success" if success else "error",
        "message": message
    }), 200 if success else 400

@app.route('/status', methods=['GET'])
def get_status():
    if not recording_manager:
        return jsonify({
            "status": "error",
            "message": "Recording manager not initialized"
        }), 400

    return jsonify({
        "status": "success",
        "is_recording": recording_manager.is_recording
    })

if __name__ == '__main__':
    # Make sure the recordings directory exists
    Path("/recordings").mkdir(exist_ok=True)
    app.run(host='0.0.0.0', port=5000)