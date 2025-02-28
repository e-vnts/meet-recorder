FROM ubuntu:22.04

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    xvfb ffmpeg pulseaudio \
    wget unzip curl \
    fonts-liberation libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdrm2 libgbm1 libnspr4 libnss3 \
    libu2f-udev libvulkan1 xdg-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

# Make run script executable
RUN chmod +x run.sh

# Create recordings directory
RUN mkdir -p recordings

# Default environment variables
ENV DISPLAY=:99
ENV PULSE_SERVER=unix:/tmp/pulseaudio.socket

# Expose port for API
EXPOSE 3000

# Start script that initializes display, audio, and runs the API
CMD ["./run.sh"]
