# services/zoom_bot.py
# Implements Selenium automation for Zoom using undetected-chromedriver to help avoid detection.
import time
import os
import logging
import undetected_chromedriver as uc  # Import undetected-chromedriver
from selenium.common.exceptions import WebDriverException

from utils import session_store

logger = logging.getLogger(__name__)

def get_chrome_driver(user_data_dir: str):
    """
    Creates and returns a Chrome WebDriver instance using undetected-chromedriver.
    The '--user-data-dir' argument ensures a separate browser profile per session.
    """
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--headless")  # Remove if browser UI is needed.
    options.add_argument(f"--user-data-dir={user_data_dir}")
    try:
        driver = uc.Chrome(options=options)
        logger.info("Undetected Chrome driver started successfully for Zoom.")
        return driver
    except Exception as e:
        logger.exception(f"Failed to start undetected Chrome driver for Zoom: {str(e)}")
        raise

def join_meeting(meeting_url: str, session_id: str):
    """
    Joins a Zoom meeting by launching a Selenium session using undetected-chromedriver.
    Updates the session status accordingly.
    """
    logger.info(f"Starting Zoom session for {meeting_url} with session_id: {session_id}")
    try:
        # Create a unique user data directory.
        user_data_dir = f"/tmp/chrome_user_data_{session_id}"
        os.makedirs(user_data_dir, exist_ok=True)
        
        # Launch the browser with undetected-chromedriver.
        driver = get_chrome_driver(user_data_dir)
        
        # Save the driver instance in our session store.
        session = session_store.get_session(session_id)
        if session is not None:
            session["driver"] = driver
        
        driver.get(meeting_url)
        logger.info(f"Navigated to Zoom URL: {meeting_url}")

        # Wait for the page to load.
        time.sleep(5)
        
        # (Optional) Insert additional steps to handle "Launch Meeting" or login flows.
        
        if session is not None:
            session["status"] = "joined"
            logger.info(f"Session {session_id} successfully joined Zoom meeting.")
    except WebDriverException as e:
        logger.exception(f"WebDriverException in Zoom session {session_id}: {str(e)}")
        session = session_store.get_session(session_id)
        if session is not None:
            session["status"] = f"error: {str(e)}"
    except Exception as e:
        logger.exception(f"Unexpected error in Zoom session {session_id}: {str(e)}")
        session = session_store.get_session(session_id)
        if session is not None:
            session["status"] = f"error: {str(e)}"

def leave_meeting(session_id: str):
    """
    Leaves a Zoom meeting by closing the undetected-chromedriver browser session.
    """
    logger.info(f"Attempting to leave Zoom session: {session_id}")
    session = session_store.get_session(session_id)
    if session and session.get("driver"):
        try:
            session["driver"].quit()
            logger.info(f"Session {session_id} closed successfully.")
        except Exception as e:
            logger.exception(f"Error closing Zoom session {session_id}: {str(e)}")
