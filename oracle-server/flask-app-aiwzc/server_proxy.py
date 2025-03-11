from flask import Flask, request, jsonify, Response, render_template, redirect, url_for, session, flash
import requests
import jwt
import logging
from datetime import datetime, timedelta
import functools
import subprocess
import json
import os
import re

app = Flask(__name__)
# Using the same secret key as your laptop server for JWT validation
app.config['SECRET_KEY'] = 'AI@WZCProject'
app.config['JWT_EXPIRATION_HOURS'] = 168  # 1 week expiration
app.config['LAPTOP_API_URL'] = 'http://10.8.0.2:5000'  # Your laptop's VPN IP and port
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)  # Session expires after 8 hours

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def require_auth_api(f):
    """Decorator to require JWT authentication for API routes."""
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

def require_auth_web(f):
    """Decorator to require session authentication for web routes."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            flash('Please log in to access this page', 'danger')
            return redirect(url_for('web_login'))
        return f(*args, **kwargs)
    return decorated

def get_vpn_peers():
    """Get WireGuard VPN peer information using pure Python networking."""
    try:
        # Create hardcoded peer list with known VPN addresses
        peers = [
            {
                'name': 'Laptop',
                'allowed_ips': '10.8.0.2/32',
                'status': 'unknown',
                'latest_handshake': 'Unknown',
                'received': 'Unknown',
                'sent': 'Unknown'
            },
            {
                'name': 'Tablet',
                'allowed_ips': '10.8.0.3/32',
                'status': 'unknown',
                'latest_handshake': 'Unknown',
                'received': 'Unknown',
                'sent': 'Unknown'
            }
        ]
        
        # Check each peer using Python socket
        import socket
        
        for peer in peers:
            ip = peer['allowed_ips'].split('/')[0]
            port = 5000 if ip == '10.8.0.2' else 8080  # Default ports
            
            try:
                # Use socket with a very short timeout to check if peer is reachable
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                result = s.connect_ex((ip, port))
                s.close()
                
                if result == 0:
                    # Port is open, peer is online
                    peer['status'] = 'online'
                    peer['latest_handshake'] = 'Recent'
                else:
                    peer['status'] = 'offline'
                    
            except Exception as e:
                logger.warning(f"Error checking {ip} with socket: {str(e)}")
                peer['status'] = 'unknown'
        
        return peers
            
    except Exception as e:
        logger.error(f"Error getting VPN peers: {str(e)}")
        return [
            {
                'name': 'Laptop',
                'allowed_ips': '10.8.0.2/32',
                'status': 'unknown'
            },
            {
                'name': 'Tablet', 
                'allowed_ips': '10.8.0.3/32',
                'status': 'unknown'
            }
        ]


def check_laptop_status():
    """Check if the laptop is online and reachable using pure Python networking."""
    laptop_ip = "10.8.0.2"
    
    # Use Python socket to check basic connectivity (similar to ping)
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((laptop_ip, 5000))
        s.close()
        logger.info(f"Successfully connected to laptop at {laptop_ip}:5000")
        return True
    except Exception as e:
        logger.warning(f"Socket connection to laptop failed: {str(e)}")
        
        # Try requests as a fallback
        try:
            response = requests.get(
                f"http://{laptop_ip}:5000/",
                timeout=2
            )
            logger.info(f"HTTP request to laptop succeeded with status {response.status_code}")
            return True
        except Exception as req_e:
            logger.warning(f"HTTP request to laptop failed: {str(req_e)}")
            return False


def get_server_token():
    """Get a valid JWT token for server-to-laptop communications."""
    return jwt.encode(
        {
            'user': 'server',
            'exp': datetime.utcnow() + timedelta(hours=app.config['JWT_EXPIRATION_HOURS'])
        },
        app.config['SECRET_KEY']
    )

# API routes
@app.route('/api/login', methods=['POST'])
def api_login():
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


# API routes with consistent /api/ prefix
@app.route('/api/status', methods=['GET'])
@require_auth_api
def api_status():
    """Get recording and inference status (API endpoint)."""
    try:
        # Check if laptop is reachable
        response = requests.get(
            f"{app.config['LAPTOP_API_URL']}/status",
            headers={
                'Authorization': request.headers.get('Authorization')
            },
            timeout=5,
            verify=False
        )
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type')
        )
    except requests.RequestException as e:
        logger.error(f"Error forwarding status request: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Could not connect to processing server (laptop)",
            "error": str(e)
        }), 503

@app.route('/api/inference_status', methods=['GET'])
@require_auth_api
def api_inference_status():
    """Get detailed inference status (API endpoint)."""
    try:
        response = requests.get(
            f"{app.config['LAPTOP_API_URL']}/inference_status",
            headers={
                'Authorization': request.headers.get('Authorization')
            },
            timeout=5,
            verify=False
        )
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type')
        )
    except requests.RequestException as e:
        logger.error(f"Error forwarding inference status request: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Could not connect to processing server (laptop)",
            "error": str(e)
        }), 503

@app.route('/api/start_recording', methods=['POST'])
@require_auth_api
def api_start_recording():
    """Start a new recording session (API endpoint)."""
    try:
        # Get request data
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Missing request body"
            }), 400
        
        # Check if rtsp_url is present
        rtsp_url = data.get('rtsp_url')
        if not rtsp_url:
            return jsonify({
                "status": "error",
                "message": "Missing rtsp_url in request body"
            }), 400
        
        # Log the request
        logger.info(f"Forwarding recording request for stream URL: {rtsp_url}")
        
        # Forward the request to the laptop
        response = requests.post(
            f"{app.config['LAPTOP_API_URL']}/start_recording",
            json=data,
            headers={
                'Authorization': request.headers.get('Authorization'),
                'Content-Type': 'application/json'
            },
            timeout=10,
            verify=False
        )
        
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type')
        )
    except requests.RequestException as e:
        logger.error(f"Error forwarding start recording request: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Could not connect to processing server (laptop)",
            "error": str(e)
        }), 503

@app.route('/api/stop', methods=['POST'])
@require_auth_api
def api_stop_recording():
    """Stop the current recording session (API endpoint)."""
    try:
        response = requests.post(
            f"{app.config['LAPTOP_API_URL']}/stop",
            headers={
                'Authorization': request.headers.get('Authorization')
            },
            timeout=10,
            verify=False
        )
        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type')
        )
    except requests.RequestException as e:
        logger.error(f"Error forwarding stop recording request: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Could not connect to processing server (laptop)",
            "error": str(e)
        }), 503


@app.route('/api/health', methods=['GET'])
def api_health_check():
    """Simple health check endpoint."""
    try:
        # Try to ping the laptop
        laptop_online = check_laptop_status()
        
        return jsonify({
            "status": "ok",
            "server": "online",
            "laptop": "online" if laptop_online else "offline",
            "vpn": "connected"
        })
    except Exception as e:
        return jsonify({
            "status": "ok",
            "server": "online",
            "laptop": "offline",
            "vpn": "error",
            "error": str(e)
        })

# Web interface routes
@app.route('/')
def home():
    """Redirect to dashboard if logged in, otherwise to login page."""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('web_login'))

@app.route('/login', methods=['GET', 'POST'])
def web_login():
    """Web login page."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == 'admin' and password == 'AI@WZCProject':
            session['user'] = username
            session['token'] = get_server_token()
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Log out user by clearing session."""
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('web_login'))

@app.route('/dashboard')
@require_auth_web
def dashboard():
    """Main dashboard showing system status."""
    # Get VPN peers
    peers = get_vpn_peers()
    
    # Check laptop status
    laptop_online = check_laptop_status()
    
    # Get recording status if laptop is online
    recording_status = None
    if laptop_online:
        try:
            response = requests.get(
                f"{app.config['LAPTOP_API_URL']}/status",
                headers={'Authorization': f"Bearer {session.get('token')}"},
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                recording_status = response.json()
        except:
            pass
    
    return render_template('dashboard.html', 
                          peers=peers, 
                          laptop_online=laptop_online,
                          recording_status=recording_status)

@app.route('/control')
@require_auth_web
def control():
    """Control panel for managing recordings."""
    # Check laptop status
    laptop_online = check_laptop_status()
    
    # Get tablet IP (if available)
    tablet_ip = None
    for peer in get_vpn_peers():
        if peer.get('name') == 'Tablet' and peer.get('status') == 'online':
            tablet_ip = peer.get('allowed_ips', '').split('/')[0]
    
    return render_template('control.html', 
                          laptop_online=laptop_online,
                          tablet_ip=tablet_ip)

@app.route('/start_recording', methods=['POST'])
@require_auth_web
def web_start_recording():
    """Web interface for starting recording with improved error handling."""
    if not check_laptop_status():
        flash('Laptop is offline. Cannot start recording.', 'danger')
        return redirect(url_for('control'))
    
    rtsp_url = request.form.get('rtsp_url')
    subject_id = request.form.get('subject_id', 'subject3')
    session_id = request.form.get('session_id', '0')
    
    if not rtsp_url:
        flash('Stream URL is required', 'danger')
        return redirect(url_for('control'))
    
    # For better UX, ensure URL has a protocol if not provided
    if not (rtsp_url.startswith('rtsp://') or rtsp_url.startswith('http://') or rtsp_url.startswith('https://')):
        # If just an IP or IP:PORT is provided, default to RTSP
        rtsp_url = f"rtsp://{rtsp_url}"
        logger.info(f"Added RTSP protocol to URL: {rtsp_url}")
    
    try:
        # Send request to laptop
        response = requests.post(
            f"{app.config['LAPTOP_API_URL']}/start_recording",
            json={
                'rtsp_url': rtsp_url,
                'subject_id': subject_id,
                'session_id': session_id
            },
            headers={'Authorization': f"Bearer {session.get('token')}"},
            timeout=15  # Longer timeout for stream connection attempts
        )
        
        result = response.json()
        
        if response.status_code == 200 and result.get('status') == 'success':
            flash('Recording started successfully', 'success')
        else:
            error_msg = result.get('message', 'Unknown error')
            flash(f'Error starting recording: {error_msg}', 'danger')
            logger.error(f"Failed to start recording with URL {rtsp_url}: {error_msg}")
    except requests.exceptions.Timeout:
        flash('Timeout while connecting to stream. Please check if the stream is accessible.', 'danger')
        logger.error(f"Timeout connecting to stream URL: {rtsp_url}")
    except Exception as e:
        flash(f'Error starting recording: {str(e)}', 'danger')
        logger.error(f"Error starting recording with URL {rtsp_url}: {str(e)}")
    
    return redirect(url_for('control'))

@app.route('/stop_recording', methods=['POST'])
@require_auth_web
def web_stop_recording():
    """Web interface for stopping recording."""
    if not check_laptop_status():
        flash('Laptop is offline. Cannot stop recording.', 'danger')
        return redirect(url_for('control'))
    
    try:
        # Send request to laptop
        response = requests.post(
            f"{app.config['LAPTOP_API_URL']}/stop",
            headers={'Authorization': f"Bearer {session.get('token')}"},
            timeout=10,
            verify=False
        )
        
        if response.status_code == 200:
            flash('Recording stopped successfully', 'success')
        else:
            flash(f'Error stopping recording: {response.json().get("message", "Unknown error")}', 'danger')
    except Exception as e:
        flash(f'Error stopping recording: {str(e)}', 'danger')
    
    return redirect(url_for('control'))


@app.route('/test_stream', methods=['POST'])
@require_auth_web
def test_stream():
    """Test if a stream URL is accessible from the laptop."""
    stream_url = request.json.get('url')
    
    if not stream_url:
        return jsonify({
            'success': False,
            'message': 'Missing stream URL'
        }), 400
    
    if not check_laptop_status():
        return jsonify({
            'success': False,
            'message': 'Laptop is offline. Cannot test stream.'
        }), 503
    
    try:
        # Forward the test request to the laptop
        response = requests.post(
            f"{app.config['LAPTOP_API_URL']}/test_stream",
            json={'url': stream_url},
            headers={'Authorization': f"Bearer {session.get('token')}"},
            timeout=10
        )
        
        # Return the laptop's response
        return jsonify(response.json()), response.status_code
    except Exception as e:
        logger.error(f"Error testing stream: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error testing stream: {str(e)}'
        }), 500


@app.route('/refresh_status', methods=['GET'])
@require_auth_web
def refresh_status():
    """AJAX endpoint to get latest recording status."""
    laptop_online = check_laptop_status()
    
    if not laptop_online:
        return jsonify({
            'laptop_online': False,
            'status': None
        })
    
    try:
        response = requests.get(
            f"{app.config['LAPTOP_API_URL']}/status",
            headers={'Authorization': f"Bearer {session.get('token')}"},
            timeout=5
        )
        
        if response.status_code == 200:
            return jsonify({
                'laptop_online': True,
                'status': response.json()
            })
        else:
            logger.warning(f"Got non-200 response from laptop: {response.status_code}")
            return jsonify({
                'laptop_online': True,  # Laptop is online but API returned error
                'status': None,
                'error': f'Failed to get status from laptop (HTTP {response.status_code})'
            })
    except Exception as e:
        logger.error(f"Error getting status from laptop: {str(e)}")
        return jsonify({
            'laptop_online': False,  # Mark as offline if request fails
            'status': None,
            'error': str(e)
        })


# Legacy routes for backward compatibility
@app.route('/api/token', methods=['POST'])
def get_api_token():
    """Dedicated endpoint for API authentication that returns a JWT token."""
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


# Legacy routes for backward compatibility
@app.route('/login', methods=['POST'])
def legacy_login():
    """Legacy login endpoint for backward compatibility."""
    # Check if it's a web browser request (Accept header contains text/html)
    if request.headers.get('Accept', '').find('text/html') >= 0:
        return web_login()
    
    # Otherwise, treat as API request
    return get_api_token()

@app.route('/status', methods=['GET'])
def legacy_status():
    """Legacy status endpoint for backward compatibility."""
    # Check if it's an API call with Authorization header
    if 'Authorization' in request.headers:
        return api_status()
    
    # Otherwise, redirect to web dashboard
    return redirect(url_for('dashboard'))

@app.route('/inference_status', methods=['GET'])
def legacy_inference_status():
    """Legacy inference status endpoint for backward compatibility."""
    # Check if it's an API call with Authorization header
    if 'Authorization' in request.headers:
        return api_inference_status()
    
    # Otherwise, redirect to web dashboard
    return redirect(url_for('dashboard'))

@app.route('/start_recording', methods=['POST'])
def legacy_start_recording():
    """Legacy start recording endpoint for backward compatibility."""
    # Check if it's an API call with JSON content type
    if request.headers.get('Content-Type', '').find('application/json') >= 0:
        return api_start_recording()
    
    # Otherwise, treat as web form submission
    return web_start_recording()

@app.route('/stop', methods=['POST'])
def legacy_stop_recording():
    """Legacy stop recording endpoint for backward compatibility."""
    # Check if it's an API call with Authorization header
    if 'Authorization' in request.headers and not request.form:
        return api_stop_recording()
    
    # Otherwise, treat as web form submission
    return web_stop_recording()


@app.context_processor
def inject_now():
    return {'now': datetime.now()}

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # We're using Nginx as a reverse proxy for SSL termination
    app.run(host='0.0.0.0', port=5000, ssl_context=None)
