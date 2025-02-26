import os
import time
import logging
import subprocess
import undetected_chromedriver as uc
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Session store example (you can replace with your own implementation)
session_store = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_session(session_id):
    return session_store.setdefault(session_id, {})

def start_virtual_display(display=":99", resolution="1280x720x24"):
    """
    Start Xvfb on the given display using -nolisten unix to avoid UNIX socket issues.
    """
    # Set DISPLAY to use TCP connection.
    os.environ["DISPLAY"] = f"localhost{display}"
    xvfb_cmd = ["Xvfb", display, "-screen", "0", resolution, "-nolisten", "unix"]
    try:
        xvfb_proc = subprocess.Popen(xvfb_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)  # Give time for Xvfb to initialize.
        logger.info(f"Xvfb virtual display started on {display} with resolution {resolution}.")
        return xvfb_proc
    except Exception as e:
        logger.exception(f"Failed to start virtual display (Xvfb): {str(e)}")
        return None

def setup_pulseaudio():
    """
    Start PulseAudio and load a null sink for virtual audio.
    """
    try:
        subprocess.run(["pulseaudio", "--start"], check=True)
        logger.info("PulseAudio started (or already running).")
    except subprocess.CalledProcessError as e:
        logger.exception("Error starting PulseAudio.")

    try:
        # Load the null sink (it may already be loaded)
        subprocess.run(
            ["pactl", "load-module", "module-null-sink", "sink_name=Virtual_Sink"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        logger.info("PulseAudio null sink 'Virtual_Sink' loaded.")
    except subprocess.CalledProcessError as e:
        logger.warning("PulseAudio null sink may already be loaded.")

def get_chrome_driver(user_data_dir: str):
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--headless=new")
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.binary_location = "/usr/bin/google-chrome"  # Adjust if needed.

    try:
        driver = uc.Chrome(options=options)
        logger.info("Undetected Chrome driver started successfully for Google Meet.")
        return driver
    except Exception as e:
        logger.exception(f"Failed to start undetected Chrome driver: {str(e)}")
        raise

def start_recording(session_id: str) -> subprocess.Popen:
    """
    Start ffmpeg to capture the Xvfb display and audio from Virtual_Sink.monitor.
    """
    output_file = f"/home/arnav/media-recorder/{session_id}.mp4"
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-f", "x11grab",
        "-s", "1280x720",
        "-i", os.environ.get("DISPLAY", ":99"),  # Use the DISPLAY variable (e.g., "localhost:99")
        "-f", "pulse",
        "-i", "Virtual_Sink.monitor",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        output_file
    ]
    try:
        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Started recording session {session_id} -> {output_file}")
        return process
    except Exception as e:
        logger.exception(f"Failed to start recording for session {session_id}: {str(e)}")
        return None

def stop_recording(proc: subprocess.Popen, session_id: str):
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
    Joins a Google Meet meeting and starts recording.
    """
    logger.info(f"Starting Google Meet session for {meeting_url} with session_id: {session_id}")

    # Start Xvfb with -nolisten unix and set DISPLAY accordingly.
    xvfb_proc = start_virtual_display(display=":99", resolution="1280x720x24")

    # Set up PulseAudio with a null sink.
    setup_pulseaudio()

    try:
        user_data_dir = f"/tmp/chrome_user_data_{session_id}"
        os.makedirs(user_data_dir, exist_ok=True)
        driver = get_chrome_driver(user_data_dir)
        session = get_session(session_id)
        session["driver"] = driver
        session["xvfb_proc"] = xvfb_proc

        # Start ffmpeg recording.
        recording_proc = start_recording(session_id)
        session["recording_proc"] = recording_proc

        # Navigate to the meeting URL.
        driver.get(meeting_url)
        logger.info(f"Navigated to Google Meet URL: {meeting_url}")
        time.sleep(5)  # Allow page to load.

        try:
            wait = WebDriverWait(driver, 15)
            name_input = wait.until(EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Your name"]')))
            name_input.clear()
            name_input.send_keys("Oracia")
            logger.info("Entered the display name: Oracia")

            ask_to_join_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//span[text()="Ask to join"]/ancestor::button[1]')))
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
    Leaves the meeting and stops recording and virtual display.
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

    recording_proc = session.get("recording_proc")
    if recording_proc:
        stop_recording(recording_proc, session_id)

    xvfb_proc = session.get("xvfb_proc")
    if xvfb_proc:
        try:
            xvfb_proc.terminate()
            xvfb_proc.wait(timeout=10)
            logger.info("Xvfb virtual display stopped.")
        except Exception as e:
            logger.exception(f"Error stopping Xvfb process: {str(e)}")

    session["status"] = "left"

# # Example usage:
# if __name__ == "__main__":
#     meeting_url = "https://meet.google.com/pez-fkct-qeg"  # Replace with your meeting URL.
#     session_id = "session123"
#     join_meeting(meeting_url, session_id)

#     # Let the meeting run for a while (example: 60 seconds).
#     time.sleep(60)

#     leave_meeting(session_id)
