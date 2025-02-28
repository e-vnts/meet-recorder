#!/bin/bash
# Run script for the Google Meet API service

# Configure environment variables (customize as needed)
export PYTHONPATH=${PYTHONPATH}:$(pwd)
export DISPLAY=${DISPLAY:-:1}
export PULSE_SERVER=${PULSE_SERVER:-localhost}

# Optional: Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Start the API service
echo "Starting Meeting Bot API service..."
uvicorn app:app --host 0.0.0.0 --port 3000 --reload
