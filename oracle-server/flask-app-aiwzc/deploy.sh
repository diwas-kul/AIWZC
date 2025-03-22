#!/bin/bash

# Exit on error
set -e

# Define colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Function to display usage
show_usage() {
    echo "Usage: $0 [build|start|stop|logs|status|reload]"
    echo "  build   - Build the Docker image"
    echo "  start   - Start the container"
    echo "  stop    - Stop and remove the container"
    echo "  logs    - Show container logs"
    echo "  status  - Check container status"
    echo "  reload  - Reload Python application without rebuilding"
}

# Function to build Docker image
build_container() {
    echo -e "${GREEN}Building AIWZC Proxy Server container...${NC}"
    docker-compose build
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Container built successfully${NC}"
    else
        echo -e "${RED}Failed to build container${NC}"
        exit 1
    fi
}

# Function to start container
start_container() {
    echo -e "${GREEN}Starting AIWZC Proxy Server...${NC}"
    
    # Check if required directories exist
    mkdir -p templates static
    
    # Check if WireGuard is active using pure bash
    if ! grep -q "wg0" /proc/net/dev 2>/dev/null; then
        echo -e "${YELLOW}Warning: WireGuard interface (wg0) not found. VPN functionality may not work.${NC}"
    fi
    
    docker-compose up -d
    
    if [ $? -eq 0 ] && docker ps | grep -q aiwzc-proxy; then
        echo -e "${GREEN}Proxy server is running!${NC}"
        echo "You can access the web interface at https://signaling.ddns.net"
    else
        echo -e "${RED}Failed to start proxy server.${NC}"
        exit 1
    fi
}

# Function to stop container
stop_container() {
    echo -e "${GREEN}Stopping AIWZC Proxy Server...${NC}"
    docker-compose down
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Container stopped successfully${NC}"
    else
        echo -e "${RED}Failed to stop container${NC}"
        exit 1
    fi
}

# Function to reload application without rebuilding
reload_application() {
    echo -e "${GREEN}Reloading AIWZC Proxy Server application...${NC}"
    
    # Check if container is running
    if ! docker ps | grep -q aiwzc-proxy; then
        echo -e "${RED}Container is not running. Please start it first.${NC}"
        exit 1
    fi
    
    # Send SIGTERM to Python process in container to restart it
    docker exec aiwzc-proxy bash -c "kill -TERM 1 || pkill -TERM python || true"
    
    echo -e "${GREEN}Application reload triggered. Check logs for details.${NC}"
}

# Function to show logs
show_logs() {
    docker logs -f aiwzc-proxy
}

# Function to check status using bash without external commands
check_status() {
    if docker ps | grep -q aiwzc-proxy; then
        echo -e "${GREEN}Proxy server is running${NC}"
        
        # Check if laptop is reachable using bash
        LAPTOP_IP="10.8.0.5"
        echo "Testing connection to laptop server..."
        
        # Use bash's built-in /dev/tcp for TCP connection test (instead of ping)
        if timeout 2 bash -c "echo > /dev/tcp/${LAPTOP_IP}/5000" 2>/dev/null; then
            echo -e "${GREEN}Laptop is reachable${NC}"
        else
            echo -e "${RED}Could not connect to laptop${NC}"
        fi
    else
        echo -e "${RED}Proxy server is not running${NC}"
    fi
}

# Main script logic
case "$1" in
    "build")
        build_container
        ;;
    "start")
        start_container
        ;;
    "stop")
        stop_container
        ;;
    "logs")
        show_logs
        ;;
    "status")
        check_status
        ;;
    "reload")
        reload_application
        ;;
    *)
        show_usage
        exit 1
        ;;
esac
