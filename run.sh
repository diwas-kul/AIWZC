#!/bin/bash

# Define variables
IMAGE_NAME="rtsp-recorder-api"
CONTAINER_NAME="rtsp-recorder"
HOST_PORT=5000
CONTAINER_PORT=5000

# Function to display usage
show_usage() {
    echo "Usage: $0 [build|run|both|stop|logs]"
    echo "  build    - Build the Docker image"
    echo "  run      - Run the container"
    echo "  both     - Build and run"
    echo "  stop     - Stop and remove the container"
    echo "  logs     - Show container logs"
}

# Function to build Docker image
build_image() {
    echo "Building Docker image..."
    docker build -t $IMAGE_NAME .
    
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
    
    # Get the absolute path to the recordings directory
    RECORDINGS_DIR="$(pwd)/recordings"
    
    # Create recordings directory if it doesn't exist
    mkdir -p "$RECORDINGS_DIR"
    
    # Set proper permissions
    chmod 700 "$RECORDINGS_DIR"
    
    echo "Starting container..."
    docker run -d \
        --name $CONTAINER_NAME \
        -p ${HOST_PORT}:${CONTAINER_PORT} \
        -v $HOME/.irods:/home/irods_user/.irods \
        -v "$RECORDINGS_DIR":/recordings \
        --restart unless-stopped \
        $IMAGE_NAME

    if [ $? -eq 0 ]; then
        echo "Container started successfully"
        echo "API is accessible at http://localhost:${HOST_PORT}"
        echo "Use the following commands to interact with the container:"
        echo "  $0 logs     - View container logs"
        echo "  $0 stop     - Stop the container"
    else
        echo "Error starting container"
        exit 1
    fi
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
    *)
        show_usage
        exit 1
        ;;
esac