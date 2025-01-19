from flask import Flask, jsonify, request
import subprocess
import threading
import logging
import functools
from datetime import datetime, timedelta
from pathlib import Path
import jwt
import time
from werkzeug.security import check_password_hash

app = Flask(__name__)
# WARNING: Change this in production!
app.config['SECRET_KEY'] = 'your-secret-key-here'  
app.config['JWT_EXPIRATION_HOURS'] = 24
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
    
    def __init__(self, rtsp_url, duration=180, irods_path="/set/home/Gait_Team/AI@WZC/VideoUpload"):
        """
        Initialize the recording manager.
        
        Args:
            rtsp_url (str): RTSP stream URL
            duration (int): Maximum recording duration in seconds
            irods_path (str): ManGO upload destination path
        """
        self.rtsp_url = rtsp_url
        self.duration = duration
        self.irods_path = irods_path
        self.is_recording = False
        self.output_dir = Path("/recordings")
        self.output_dir.mkdir(exist_ok=True)
        self.process = None
        self._upload_thread = None
        self._recording_start_time = None

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
                "-o", str(self.output_dir)
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
                # Calculate remaining duration
                elapsed_time = time.time() - self._recording_start_time
                remaining_duration = max(0, self.duration - elapsed_time)
                
                logger.info(f"Stopping recording after {elapsed_time:.2f} seconds")
                
                # Let the process finish naturally if close to completion
                if remaining_duration < 10:  # If less than 10 seconds remaining
                    self.process.wait()
                else:
                    # Send terminate signal and wait for completion
                    self.process.terminate()
                    self.process.wait()
                
                # Wait for upload to complete
                if self._upload_thread:
                    self._upload_thread.join(timeout=app.config['UPLOAD_TIMEOUT'])
                    
                return True, "Recording stopped and saved successfully"
        except Exception as e:
            logger.error(f"Error stopping recording: {str(e)}")
            return False, str(e)

    def _handle_recording_completion(self):
        """Handle the recording completion and ManGO upload process."""
        try:
            # Wait for recording to complete
            self.process.wait()
            
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
                        latest_recording.unlink()
                        logger.info(f"Removed local file: {latest_recording}")
                    else:
                        logger.error(f"Upload failed: {upload_process.stderr}")
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

# Global recording manager instance
recording_manager = None

@app.route('/login', methods=['POST'])
def login():
    """Authenticate user and return JWT token."""
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        return jsonify({'message': 'Missing credentials'}), 401
    
    # WARNING: Replace with secure authentication in production
    if auth.username == "admin" and auth.password == "your-secure-password":
        token = jwt.encode(
            {
                'user': auth.username,
                'exp': datetime.utcnow() + timedelta(hours=app.config['JWT_EXPIRATION_HOURS'])
            },
            app.config['SECRET_KEY']
        )
        return jsonify({'token': token})
    
    return jsonify({'message': 'Invalid credentials'}), 401

@app.route('/init/<path:rtsp_url>', methods=['POST'])
@require_auth
def initialize(rtsp_url):
    """Initialize recording manager with RTSP URL."""
    global recording_manager
    try:
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
@require_auth
def start_recording():
    """Start recording from initialized RTSP stream."""
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
    """Get current recording status."""
    if not recording_manager:
        return jsonify({
            "status": "error",
            "message": "Recording manager not initialized"
        }), 400

    recording_time = None
    if recording_manager._recording_start_time:
        recording_time = time.time() - recording_manager._recording_start_time

    return jsonify({
        "status": "success",
        "is_recording": recording_manager.is_recording,
        "recording_time": recording_time
    })

if __name__ == '__main__':
    # Make sure the recordings directory exists
    Path("/recordings").mkdir(exist_ok=True)
    # WARNING: In production, use proper SSL certificates
    app.run(host='0.0.0.0', port=5000, ssl_context='adhoc')