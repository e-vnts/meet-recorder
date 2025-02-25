import undetected_chromedriver as uc
import os
import time
import logging
import subprocess
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Replace this with your own session store implementation
session_store = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_session(session_id):
    return session_store.setdefault(session_id, {})

def get_chrome_driver(user_data_dir: str):
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")

    # Uncomment if you do not want to see the UI:
    options.add_argument("--headless=new")
    options.add_argument(f"--user-data-dir={user_data_dir}")
    # Adjust path if needed:
    options.binary_location = "/usr/bin/google-chrome"

    try:
        driver = uc.Chrome(options=options)
        logger.info("Undetected Chrome driver started successfully for Google Meet.")
        return driver
    except Exception as e:
        logger.exception(f"Failed to start undetected Chrome driver: {str(e)}")
        raise

def start_recording(session_id: str) -> subprocess.Popen:
    """
    Start an ffmpeg process to capture screen & audio.
    Returns the Popen object so we can stop it later.
    """
    # We'll store recordings in /tmp/ using session_id as the filename
    output_file = f"/tmp/{session_id}.mp4"
    # Example ffmpeg command capturing from Xvfb :99 at 1280x720 resolution
    # and from default PulseAudio device. Adjust as needed.
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-f", "x11grab",
        "-s", "1280x720",
        "-i", ":99",           # X display
        "-f", "pulse",
        "-i", "default",       # PulseAudio default device
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        output_file
    ]

    try:
        # Run ffmpeg silently by redirecting stdout/stderr
        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Started recording session {session_id} -> {output_file}")
        return process
    except Exception as e:
        logger.exception(f"Failed to start recording for session {session_id}: {str(e)}")
        return None

def stop_recording(proc: subprocess.Popen, session_id: str):
    """
    Stop the ffmpeg process gracefully.
    """
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
        logger.info(f"Stopped recording session {session_id}")
    except Exception as e:
        logger.exception(f"Failed to stop recording session {session_id}: {str(e)}")

def join_meeting(meeting_url: str, session_id: str):
    """
    Joins a Google Meet meeting, enters a display name, clicks Ask to join,
    then starts recording.
    """
    logger.info(f"Starting Google Meet session for {meeting_url} with session_id: {session_id}")
    try:
        # Create a unique user data directory.
        user_data_dir = f"/tmp/chrome_user_data_{session_id}"
        os.makedirs(user_data_dir, exist_ok=True)

        driver = get_chrome_driver(user_data_dir)
        session = get_session(session_id)
        session["driver"] = driver

        # Start the recording process
        recording_proc = start_recording(session_id)
        session["recording_proc"] = recording_proc

        # Navigate to the Meet URL
        driver.get(meeting_url)
        logger.info(f"Navigated to Google Meet URL: {meeting_url}")

        # Wait for the page to load
        time.sleep(5)

        # Enter name & click "Ask to join"
        try:
            wait = WebDriverWait(driver, 15)

            # 1) Fill the name "Arnav Bot" in the text box
            name_input = wait.until(
                EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Your name"]'))
            )
            name_input.clear()
            name_input.send_keys("Oracia")
            logger.info("Entered the display name: Arnav Bot")

            # 2) Click "Ask to join" button
            ask_to_join_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//span[text()="Ask to join"]/ancestor::button[1]'))
            )
            ask_to_join_button.click()
            logger.info("Clicked the 'Ask to join' button.")
        except TimeoutException:
            logger.warning("Name input or 'Ask to join' button not found in time.")

        session["status"] = "joined"
        logger.info(f"Session {session_id} successfully joined Google Meet.")

    except WebDriverException as e:
        logger.exception(f"WebDriverException in Google Meet session {session_id}: {str(e)}")
        session = get_session(session_id)
        session["status"] = f"error: {str(e)}"
    except Exception as e:
        logger.exception(f"Unexpected error in Google Meet session {session_id}: {str(e)}")
        session = get_session(session_id)
        session["status"] = f"error: {str(e)}"

def leave_meeting(session_id: str):
    """
    Leaves the meeting, stops the recording.
    """
    logger.info(f"Attempting to leave Google Meet session: {session_id}")
    session = get_session(session_id)
    driver = session.get("driver")
    if driver:
        try:
            driver.quit()
            logger.info(f"Session {session_id} closed successfully.")
        except Exception as e:
            logger.exception(f"Error closing session {session_id}: {str(e)}")

    # Stop recording
    recording_proc = session.get("recording_proc")
    if recording_proc:
        stop_recording(recording_proc, session_id)

    session["status"] = "left"
