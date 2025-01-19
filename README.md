# AIWZC

Codebase for a Flask-based web app that records RTSP video streams and automatically uploads them to ManGO. 

## Prerequisites

1. Docker installed on the host machine
2. ManGO account and iCommands configuration
3. VPN access to the network where RTSP streams are hosted
4. Machine with sufficient storage for temporary video recordings

## Quick Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd rtsp-recorder-api
```

2. Configure ManGO iCommands:
```bash
# Copy your .irods directory to your home directory
cp -r /path/to/your/.irods $HOME/
```

3. Build and run:
```bash
chmod +x run.sh
./run.sh both
```

The API will be accessible at `https://your-server:5000`

## Security Configuration

Before deploying, update the following security settings in `api_server.py`:

```python
# Change these values
app.config['SECRET_KEY'] = 'your-secure-secret-key'  
default_username = 'your-username'
default_password = 'your-secure-password'
```

## API Usage

1. Get authentication token:
```bash
curl -X POST -u username:password https://your-server:5000/login
```

2. Initialize with RTSP URL:
```bash
curl -X POST \
  -H "Authorization: Bearer your-token" \
  https://your-server:5000/init/rtsp://camera-ip:port/stream
```

3. Start recording:
```bash
curl -X POST \
  -H "Authorization: Bearer your-token" \
  https://your-server:5000/start
```

4. Stop recording:
```bash
curl -X POST \
  -H "Authorization: Bearer your-token" \
  https://your-server:5000/stop
```

5. Check status:
```bash
curl -H "Authorization: Bearer your-token" \
  https://your-server:5000/status
```


## Container Management

Start container:
```bash
./run.sh run
```

View logs:
```bash
./run.sh logs
```

Stop container:
```bash
./run.sh stop
```

## Recording Storage

- Temporary recordings are stored in `./recordings/`
- Videos are automatically uploaded to ManGO after completion
- Local recordings are deleted after successful upload

