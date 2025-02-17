# AIWZC

Codebase for a Flask-based web app that records RTSP video streams, automatically uploads them to ManGO, and performs AI-based exercise analysis.

## Prerequisites

1. Docker installed on the host machine with NVIDIA container toolkit
2. ManGO account and iCommands configuration
3. VPN access to the network where RTSP streams are hosted
4. Machine with sufficient storage for temporary video recordings
5. NVIDIA GPU with CUDA 11.8 support

## Quick Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd aiwzc
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

The API will be accessible at http://localhost:5000

## Security Configuration

Before deploying, update the following security settings in `api_server.py`:

```python
# Change these values
app.config['SECRET_KEY'] = 'your-secure-secret-key'  
default_username = 'admin'
default_password = 'your-secure-password'
```

## API Usage

### Authentication

Get an authentication token (valid for 24 hours):
```bash
curl -X POST -u admin:AI@WZCProject http://localhost:5000/login
```

Store the returned token for use in subsequent requests:
```bash
export TOKEN="your-token-here"
```

### Recording and Inference

1. Initialize with RTSP URL and session info:
```bash
curl -X GET \
  -H "Authorization: Bearer $TOKEN" \
  'http://localhost:5000/init/rtsp://camera-ip:port/stream?subject_id=subject3&session_id=0'
```

2. Start recording:
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/start
```

3. Stop recording:
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/stop
```

4. Check recording and inference status:
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/status
```

5. Get detailed inference queue status:
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/inference_status
```

### Example Workflow

Here's a complete example of recording two exercise sessions:

```bash
# Get authentication token
TOKEN=$(curl -s -X POST -u admin:AI@WZCProject http://localhost:5000/login | jq -r '.token')

# First recording
curl -X GET \
  -H "Authorization: Bearer $TOKEN" \
  'http://localhost:5000/init/rtsp://camera-ip:port/stream?subject_id=subject3&session_id=0'

curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:5000/start
echo "Recording first session... (waiting 3 minutes)"
sleep 180
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:5000/stop

# Second recording
curl -X GET \
  -H "Authorization: Bearer $TOKEN" \
  'http://localhost:5000/init/rtsp://camera-ip:port/stream?subject_id=subject3&session_id=1'

curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:5000/start
echo "Recording second session... (waiting 3 minutes)"
sleep 180
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:5000/stop

# Monitor status
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/status
```

### Understanding Status Output

The status endpoint provides comprehensive information:

```json
{
  "status": "success",
  "recording": {
    "is_recording": false,
    "recording_time": null
  },
  "inference": {
    "current_task": {
      "status": "processing",
      "video_path": "/recordings/recording_20250217_012511.mp4",
      "subject_id": "subject3",
      "session_id": "0",
      "timing": {
        "recording_timestamp": "2025-02-17T01:25:11",
        "queue_add_time": "2025-02-17T01:28:17",
        "processing_start_time": "2025-02-17T01:28:17",
        "time_since_recording": 180.5,
        "time_in_queue": 0.5,
        "processing_time": 35.2
      }
    },
    "queue_length": 1,
    "pending_tasks": [...]
  }
}
```

### Recording Flow

1. Recording is saved locally
2. Automatically uploaded to ManGO
3. Queued for inference processing
4. Inference results saved to exercise_outcomes folder
5. Original recording deleted after successful upload

## Inference Results

Inference results are stored in `Inference/exercise_outcomes/` with the format:
```json
{
  "subject_id": "subject3",
  "session_id": "0",
  "exercise_outcomes": {
    "exercise_duration": { ... },
    "repetition_count": { ... },
    "motion_variability": { ... }
  }
}
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

## Technical Details

- Recordings are temporarily stored in `./recordings/`
- Videos are automatically uploaded to ManGO after completion
- Inference tasks are queued and processed sequentially
- Completed task logs are stored in `/app/logs/inference_tasks.log`