import undetected_chromedriver as uc
import os
import time
import logging
from selenium.common.exceptions import WebDriverException
from utils import session_store


logger = logging.getLogger(__name__)

def get_chrome_driver(user_data_dir: str):
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # options.add_argument("--headless")  # Remove this flag if you want to see the browser UI.
    options.add_argument(f"--user-data-dir={user_data_dir}")
    # Explicitly set the Chrome binary location
    options.binary_location = "/usr/bin/google-chrome"  # Adjust path if needed

    try:
        driver = uc.Chrome(options=options)
        logger.info("Undetected Chrome driver started successfully for Google Meet.")
        return driver
    except Exception as e:
        logger.exception(f"Failed to start undetected Chrome driver: {str(e)}")
        raise
  

def join_meeting(meeting_url: str, session_id: str):
    """
    Joins a Google Meet meeting by launching a Selenium session using undetected-chromedriver.
    Updates the session status accordingly.
    """
    logger.info(f"Starting Google Meet session for {meeting_url} with session_id: {session_id}")
    try:
        # Create a unique user data directory.
        user_data_dir = f"/tmp/chrome_user_data_{session_id}"
        os.makedirs(user_data_dir, exist_ok=True)
        
        # Launch the browser with undetected-chromedriver.
        driver = get_chrome_driver(user_data_dir)
        
        # Store the driver instance in our session store.
        session = session_store.get_session(session_id)
        if session is not None:
            session["driver"] = driver
        
        driver.get(meeting_url)
        logger.info(f"Navigated to Google Meet URL: {meeting_url}")

        # Wait for the page to load.
        time.sleep(5)  # In production, consider using WebDriverWait.
        
        # (Optional) Insert additional steps to handle login or "Ask to join" prompts.
        
        if session is not None:
            session["status"] = "joined"
            logger.info(f"Session {session_id} successfully joined Google Meet.")
    except WebDriverException as e:
        logger.exception(f"WebDriverException in Google Meet session {session_id}: {str(e)}")
        session = session_store.get_session(session_id)
        if session is not None:
            session["status"] = f"error: {str(e)}"
    except Exception as e:
        logger.exception(f"Unexpected error in Google Meet session {session_id}: {str(e)}")
        session = session_store.get_session(session_id)
        if session is not None:
            session["status"] = f"error: {str(e)}"

def leave_meeting(session_id: str):
    """
    Leaves a Google Meet meeting by closing the undetected-chromedriver browser session.
    """
    logger.info(f"Attempting to leave Google Meet session: {session_id}")
    session = session_store.get_session(session_id)
    if session and session.get("driver"):
        try:
            session["driver"].quit()
            logger.info(f"Session {session_id} closed successfully.")
        except Exception as e:
            logger.exception(f"Error closing session {session_id}: {str(e)}")
