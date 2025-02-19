#!/bin/bash

# Define variables
IMAGE_NAME="aiwzc-server"
CONTAINER_NAME="aiwzc-server"
HOST_PORT=5000
CONTAINER_PORT=5000

# Function to display usage
show_usage() {
    echo "Usage: $0 [build|run|both|stop|logs|demo]"
    echo "  build    - Build the Docker image"
    echo "  run      - Run the container"
    echo "  both     - Build and run"
    echo "  stop     - Stop and remove the container"
    echo "  logs     - Show container logs"
    echo "  demo     - Run Inference/pilot.py"
}

# Check GPU availability
check_gpu() {
    if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
        echo "GPU detected"
        return 0
    else
        echo "No GPU detected, running in CPU mode"
        return 1
    fi
}

# Function to build Docker image
build_image() {
    echo "Checking GPU availability for build..."
    if check_gpu; then
        echo "Building GPU-enabled Docker image..."
        docker build -t $IMAGE_NAME -f Dockerfile.gpu .
    else
        echo "Building CPU-only Docker image..."
        docker build -t $IMAGE_NAME -f Dockerfile.cpu .
    fi
    
    if [ $? -eq 0 ]; then
        echo "Image built successfully"
    else
        echo "Error building image"
        exit 1
    fi
}


# Function to run container
run_container() {
    echo "Checking for existing container..."
    if docker ps -a | grep -q $CONTAINER_NAME; then
        echo "Removing existing container..."
        docker rm -f $CONTAINER_NAME
    fi
    
    # Get the absolute path to the directories
    RECORDINGS_DIR="$(pwd)/recordings"
    INFERENCE_DIR="$(pwd)/Inference"
    
    # Create necessary directories
    mkdir -p "$RECORDINGS_DIR"
    
    # Set proper permissions
    chmod 700 "$RECORDINGS_DIR"

    # Add host.docker.internal mapping based on OS
    if [ "$(uname)" == "Linux" ]; then
        DOCKER_HOST_FLAG="--add-host=host.docker.internal:host-gateway"
    else
        DOCKER_HOST_FLAG=""  # Not needed for macOS/Windows as it's automatic
    fi
    
    # Check GPU availability and construct docker run command accordingly
    if check_gpu; then
        echo "Starting container with GPU support..."
        docker run -d \
            $DOCKER_HOST_FLAG \
            --gpus all \
            --name $CONTAINER_NAME \
            -p ${HOST_PORT}:${CONTAINER_PORT} \
            -v $HOME/.irods:/home/irods_user/.irods \
            -v "$RECORDINGS_DIR":/recordings \
            -v "$INFERENCE_DIR":/app/Inference \
            --restart unless-stopped \
            $IMAGE_NAME
    else
        echo "Starting container without GPU support..."
        docker run -d \
            $DOCKER_HOST_FLAG \
            --name $CONTAINER_NAME \
            -p ${HOST_PORT}:${CONTAINER_PORT} \
            -v $HOME/.irods:/home/irods_user/.irods \
            -v "$RECORDINGS_DIR":/recordings \
            -v "$INFERENCE_DIR":/app/Inference \
            --restart unless-stopped \
            $IMAGE_NAME
    fi

    if [ $? -eq 0 ]; then
        echo "Container started successfully"
        echo "API is accessible at http://localhost:${HOST_PORT}"
        echo "Use the following commands to interact with the container:"
        echo "  $0 logs     - View container logs"
        echo "  $0 stop     - Stop the container"
        echo "  $0 demo     - Run video demo"
    else
        echo "Error starting container"
        exit 1
    fi
}

# Function to run video demo
run_demo() {
    echo "Running video demo..."
    docker exec -it $CONTAINER_NAME \
        bash -c "cd /app/Inference && python3 pilot.py"
}

# Function to stop container
stop_container() {
    echo "Stopping container..."
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
    echo "Container stopped and removed"
}

# Function to show logs
show_logs() {
    docker logs -f $CONTAINER_NAME
}

# Main script logic
case "$1" in
    "build")
        build_image
        ;;
    "run")
        run_container
        ;;
    "both")
        build_image
        run_container
        ;;
    "stop")
        stop_container
        ;;
    "logs")
        show_logs
        ;;
    "demo")
        run_demo
        ;;
    *)
        show_usage
        exit 1
        ;;
esac