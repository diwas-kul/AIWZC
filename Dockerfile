FROM python:3.8-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    wget \
    gnupg2 \
    lsb-release \
    && rm -rf /var/apt/lists/*

# Install iCommands
RUN wget -qO - https://packages.irods.org/irods-signing-key.asc | apt-key add - \
    && echo "deb [arch=amd64] https://packages.irods.org/apt/ $(lsb_release -sc) main" \
    | tee /etc/apt/sources.list.d/renci-irods.list \
    && apt-get update \
    && apt-get install -y irods-icommands \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

# Copy the Python scripts
COPY rtsp_recorder.py api_server.py /app/

# Create necessary directories
RUN mkdir -p /recordings /root/.irods

WORKDIR /app

# Start the API server
CMD ["python", "api_server.py"]