FROM python:3.8-slim

# Install required packages
RUN apt-get update && apt-get install -y \
    curl \
    sudo \
    wireguard \
    iptables \
    procps \
    iproute2 \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy application files
COPY requirements.txt ./

# Templates directory
RUN mkdir -p /app/templates /app/static

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create directory for sudoers.d
RUN mkdir -p /etc/sudoers.d

# Add sudoers configuration to allow running wg without password
RUN echo "www-data ALL=(ALL) NOPASSWD: /usr/bin/wg" > /etc/sudoers.d/wg-nopasswd && \
    chmod 0440 /etc/sudoers.d/wg-nopasswd

# Expose the Flask port
EXPOSE 5000

# Start the proxy server
CMD ["python", "server_proxy.py"]
