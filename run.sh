#!/bin/bash

# Define variables
IMAGE_NAME="rtsp-recorder-api"
CONTAINER_NAME="rtsp-recorder"

# Function to build Docker image
build_image() {
    echo "Building Docker image..."
    docker build -t $IMAGE_NAME .
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
    chown -R $USER:$USER "$RECORDINGS_DIR"
    chmod 700 "$RECORDINGS_DIR"
    
    echo "Starting container..."
    docker run -d \
        --name $CONTAINER_NAME \
        --network=host \
        -v $HOME/.irods:/home/irods_user/.irods \
        -v "$RECORDINGS_DIR":/recordings \
        --restart unless-stopped \
        $IMAGE_NAME

    if [ $? -eq 0 ]; then
        echo "Container started successfully"
        echo "Container logs will follow:"
        docker logs -f $CONTAINER_NAME
    fi
}

case "$1" in
    "build")
        build_image
        ;;
    "run")
        run_container
        ;;
    "both"|"")
        build_image
        run_container
        ;;
    *)
        echo "Usage: $0 [build|run|both]"
        exit 1
        ;;
esac