# Google Meet Recording Bot with API

This service provides a REST API for controlling a headless Chrome browser that can join and record Google Meet sessions.

## Features

- Join Google Meet sessions using API endpoints
- Record audio and video from meetings
- Control multiple concurrent meeting sessions
- Monitor session status and recording progress
- Support for both headless and visible browser modes

## Requirements

- Python 3.8+
- Chrome or Chromium browser
- Xvfb for headless display
- FFmpeg for recording
- PulseAudio for audio capture

## Installation

1. Install system dependencies:

   ```bash
   sudo apt-get update
   sudo apt-get install -y xvfb pulseaudio ffmpeg
   ```

2. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Folder Structure

```
my_meeting_bot/
├── app.py                   # Main FastAPI entry point
├── controllers/
│   └── meeting_controller.py  # API endpoints for join, status, leave
├── services/
│   ├── google_meet_bot.py     # Google Meet automation using undetected‑chromedriver
│   └── zoom_bot.py            # Zoom automation using undetected‑chromedriver
├── utils/
│   └── session_store.py       # In-memory session store for tracking sessions
├── requirements.txt         # Python dependencies
├── Dockerfile               # Docker build instructions (installs Chrome 114)
├── .gitignore               # Files to ignore in Git
└── README.md                # This file
```

## How to Build and Run with Docker

1. **Build the Docker Image:**

   In your project directory (where the Dockerfile is located), run:

   ```bash
   docker build -t my-meeting-bot .
   ```

2. **Run the Docker Container:**

   Once built, run the container exposing port 3000:

   ```bash
   docker run -p 3000:3000 my-meeting-bot
   ```

   This starts the FastAPI server on port 3000.

## API Endpoints

- **POST /join**

  Join a meeting by sending a JSON request:

  ```json
  {
    "meetingUrl": "https://meet.google.com/abc-defg-hij",
    "platform": "google"
  }
  ```

- **GET /status/{sessionId}**

  Retrieve the status of the meeting session (e.g., `joining`, `joined`, or an error).

- **POST /leave**

  Leave a meeting by providing the session ID:

  ```json
  {
    "sessionId": "your-session-id"
  }
  ```

## Additional Notes

- **Chrome Version:**  
  This Dockerfile installs Google Chrome version 114 (as defined by the environment variable `CHROME_VERSION`). This is required to match the driver requirements for undetected‑chromedriver used in this project.

- **Logging and Error Handling:**  
  The application logs key events and errors to the console. Check the container logs for troubleshooting.

- **Local Development:**  
  If you prefer to run the application outside of Docker, see the README section on running with Python on WSL.

## Requirements

- Docker (if using Docker)
- Alternatively, Python 3.9+, pip, and a proper Chrome installation if running locally.

## License

[MIT License](LICENSE) *(if applicable)*


