#!/bin/bash
set -e

# Set up WireGuard if config exists
if [ -f "/etc/wireguard/wg0.conf" ]; then
    echo "Setting up WireGuard with provided configuration..."
    chmod 600 /etc/wireguard/wg0.conf
    
    # Install resolvconf if it's missing
    if ! command -v resolvconf &> /dev/null; then
        apt-get update && apt-get install -y openresolv
    fi
    
    # Clean up any existing interface with the same name
    if ip link show wg0 &> /dev/null; then
        echo "WireGuard interface already exists, removing it first..."
        ip link delete wg0
    fi
    
    # Extract IP address from config file
    WG_IP=$(grep "Address" /etc/wireguard/wg0.conf | cut -d '=' -f 2 | tr -d ' ' | cut -d '/' -f 1)
    WG_CIDR=$(grep "Address" /etc/wireguard/wg0.conf | cut -d '=' -f 2 | tr -d ' ' | cut -d '/' -f 2)
    
    echo "Configuring WireGuard with IP: $WG_IP/$WG_CIDR"
    
    # Manual WireGuard setup (more reliable in containers)
    ip link add dev wg0 type wireguard
    
    # Apply WireGuard configuration
    if grep -q "PrivateKey" /etc/wireguard/wg0.conf; then
        # Configuration contains embedded private key
        wg setconf wg0 <(wg-quick strip wg0)
    else
        # Private key is in a separate file
        PRIVATE_KEY_PATH=$(grep "PrivateKey" /etc/wireguard/wg0.conf | cut -d '=' -f 2 | tr -d ' ')
        if [ -f "$PRIVATE_KEY_PATH" ]; then
            PRIVATE_KEY=$(cat "$PRIVATE_KEY_PATH")
            # Get peer info
            PEER_PUBKEY=$(grep "PublicKey" /etc/wireguard/wg0.conf | cut -d '=' -f 2 | tr -d ' ')
            ENDPOINT=$(grep "Endpoint" /etc/wireguard/wg0.conf | cut -d '=' -f 2 | tr -d ' ')
            ALLOWED_IPS=$(grep "AllowedIPs" /etc/wireguard/wg0.conf | cut -d '=' -f 2 | tr -d ' ')
            
            # Setup with wg command
            echo "Setting interface with extracted configuration..."
            wg set wg0 private-key <(echo "$PRIVATE_KEY") peer "$PEER_PUBKEY" endpoint "$ENDPOINT" allowed-ips "$ALLOWED_IPS"
        else
            echo "ERROR: Private key file not found at $PRIVATE_KEY_PATH"
            exit 1
        fi
    fi
    
    # Configure IP address and bring up interface
    ip addr add "$WG_IP/$WG_CIDR" dev wg0
    ip link set mtu 1420 up dev wg0
    
    # Extract AllowedIPs to set routes
    ALLOWED_IPS=$(grep "AllowedIPs" /etc/wireguard/wg0.conf | cut -d '=' -f 2 | tr -d ' ')
    
    # Set routes for all allowed IPs
    for allowed_ip in $(echo $ALLOWED_IPS | tr ',' ' '); do
        echo "Adding route for $allowed_ip"
        if ! ip route add $allowed_ip dev wg0 2>/dev/null; then
            echo "Route for $allowed_ip already exists or couldn't be added"
        fi
    done
    
    echo "WireGuard interface configured"
    
    # Show WireGuard configuration
    echo "WireGuard configuration:"
    wg show wg0
    
    # Test connectivity to the WireGuard network
    echo "Testing WireGuard connectivity..."
    ping -c 3 10.8.0.1 || echo "Warning: Could not ping 10.8.0.1, but continuing..."
fi

# Start the Flask API server
echo "Starting API server..."
cd /app
# Use the same gunicorn configuration as in the original Dockerfile
su -c "gunicorn --bind 0.0.0.0:5000 --workers 1 --timeout 300 api_server:app" irods_user &

# Keep container running
echo "Container setup complete, services running."
exec tail -f /dev/null
