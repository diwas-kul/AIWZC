FROM python:3.8-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    wget \
    gnupg2 \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Install iCommands
RUN wget -qO - https://packages.irods.org/irods-signing-key.asc | apt-key add - \
    && echo "deb [arch=amd64] https://packages.irods.org/apt/ $(lsb_release -sc) main" \
    | tee /etc/apt/sources.list.d/renci-irods.list \
    && apt-get update \
    && apt-get install -y irods-icommands \
    && rm -rf /var/lib/apt/lists/*

# Create a user with the same UID as your host user (default 1000)
RUN useradd -u 1000 -m irods_user \
    && mkdir -p /recordings \
    && chown -R irods_user:irods_user /recordings

# Set up application directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application files
COPY api_server.py rtsp_recorder.py ./
RUN chown -R irods_user:irods_user /app

# Switch to non-root user
USER irods_user

# Expose the Flask port
EXPOSE 5000

# Start the API server using gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "300", "api_server:app"]