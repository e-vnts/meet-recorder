# app.py
# Main entry point for the FastAPI application with logging configuration.
import logging
from fastapi import FastAPI
from controllers import meeting_controller

# Configure logging for the application.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logger.info("Starting My Meeting Bot application...")

app = FastAPI(title="My Meeting Bot")

# Include the meeting controller routes in the main app.
app.include_router(meeting_controller.router)

# If running directly (e.g., python app.py), use uvicorn to launch the server.
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=3000, reload=True)
