# services/zoom_bot.py
# Implements Selenium automation for Zoom using undetected-chromedriver to help avoid detection.
import time
import os
import logging
import undetected_chromedriver as uc  # Import undetected-chromedriver
from selenium.common.exceptions import WebDriverException

# Import for explicit waits and locators:
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from utils import session_store

logger = logging.getLogger(__name__)

def convert_zoom_url(url):
    # Extract meeting id by finding '/j/' and taking the substring until the next '?'
    try:
        j_index = url.index("/j/")
        start = j_index + len("/j/")
        q_index = url.find("?", start)
        if q_index == -1:
            meeting_id = url[start:]
        else:
            meeting_id = url[start:q_index]
    except ValueError:
        raise ValueError("URL does not contain '/j/' in the expected format.")

    # Extract the password by locating "pwd=" and taking the substring until the next '&' if present.
    pwd_marker = "pwd="
    pwd_index = url.find(pwd_marker)
    if pwd_index == -1:
        raise ValueError("URL does not contain a 'pwd=' parameter.")
    pwd_start = pwd_index + len(pwd_marker)
    amp_index = url.find("&", pwd_start)
    if amp_index == -1:
        pwd = url[pwd_start:]
    else:
        pwd = url[pwd_start:amp_index]

    # Construct the new URL using string concatenation.
    new_url = "https://app.zoom.us/wc/" + meeting_id + "/join?fromPWA=1&pwd=" + pwd
    return new_url

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
    options.binary_location = "/usr/bin/google-chrome"  # Adjust path if needed

    try:
        driver = uc.Chrome(options=options)
        logger.info("Undetected Chrome driver started successfully for Zoom.")
        return driver
    except Exception as e:
        logger.exception(f"Failed to start undetected Chrome driver for Zoom: {str(e)}")
        raise

def find_element_in_frames(driver, by, value, timeout=20):
    """
    Attempts to locate an element using the given locator.
    First tries the default content; if not found, iterates over iframes.
    """
    try:
        # Try to locate element in the default content.
        return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))
    except Exception:
        # If not found, try inside all iframes.
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                element = WebDriverWait(driver, 5).until(EC.presence_of_element_located((by, value)))
                return element
            except Exception:
                driver.switch_to.default_content()
        raise Exception(f"Element with locator ({by}, {value}) not found in any frame.")

def join_meeting(meeting_url: str, session_id: str):
    """
    Joins a Zoom meeting by launching a Selenium session using undetected-chromedriver.
    Updates the session status accordingly.
    """

    meeting_url = convert_zoom_url(meeting_url)
    
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

        # -------------------------------------------------------------------
        #  Modified snippet: use explicit waits and search in frames for the name input and Join button.
        # -------------------------------------------------------------------
        try:
            # Locate the input element by its ID "input-for-name" (may be inside an iframe)
            name_input = find_element_in_frames(driver, By.ID, "input-for-name", timeout=20)
            name_input.clear()
            name_input.send_keys("Oracia")
            
            # Locate the Join button by its text "Join"
            join_button = find_element_in_frames(driver, By.XPATH, "//button[text()='Join']", timeout=20)
            join_button.click()
            logger.info("Successfully filled in name 'Oracia' and clicked 'Join'.")
        except Exception as e:
            logger.exception(f"Could not fill in name or click 'Join': {e}")
        # -------------------------------------------------------------------
        
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
