import os
import time
import logging
import subprocess
import threading

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
def handle_popups(driver, logger=None, timeout=3):
    """
    Looks for common pop-ups or info boxes in Google Meet
    and dismisses them if present. Adjust XPaths or text as needed.
    """
    if logger is None:
        import logging
        logger = logging.getLogger(__name__)
    
    # List of (XPATH, description) pairs for popups to dismiss
    popup_selectors = [
        # Example: "Got it" button
        ('//span[text()="Got it"]', 'Got it'),
        # If there's a "Sign in with your Google account" or "Allow microphone and camera" popup
        # you can add additional selectors here:
        # ('//span[text()="Sign in"]', 'Sign in prompt'),
        # ('//span[contains(text(), "Allow microphone and camera")]', 'Allow mic/cam prompt'),
    ]

    # Try each popup selector
    for xpath, desc in popup_selectors:
        try:
            # Wait up to 'timeout' seconds for the element to be clickable
            elem = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            elem.click()
            logger.info(f"Dismissed '{desc}' popup.")
        except (NoSuchElementException, TimeoutException):
            # If not found or not clickable, ignore
            pass
        except Exception as e:
            logger.warning(f"Could not dismiss '{desc}' popup: {e}")
def periodic_popup_handler(driver, logger):
    while True:
        try:
            handle_popups(driver, logger=logger, timeout=2)
            time.sleep(5)  # check every 5 seconds
        except Exception as e:
            logger.warning(f"Popup handler encountered an error: {e}")
            break


# --- Configuration from environment variables ---
meet_link = os.environ.get("GMEET_LINK")
if not meet_link:
    raise RuntimeError("GMEET_LINK environment variable must be set to the Google Meet URL.")

record_path = os.environ.get("RECORDING_PATH", "recordings/output.mp4")
display_num = os.environ.get("DISPLAY_NUM", "99")
screen_res = os.environ.get("SCREEN_RESOLUTION", "1280x720")
screen_depth = os.environ.get("SCREEN_DEPTH", "24")
display_name = os.environ.get("DISPLAY_NAME", "Oracia")  # Name to use if joining as guest

# Chrome configuration
chrome_path = os.environ.get("CHROME_BINARY")  # Optional custom Chrome binary path
user_data_dir = os.environ.get("CHROME_USER_DATA_DIR", "/tmp/meet_bot_profile")

# SHOW_BROWSER environment variable:
# Set to "true" if you want the browser window visible.
show_browser = os.environ.get("SHOW_BROWSER", "true").lower() in ("true", "1", "yes")

# NO_XVFB environment variable:
# Set to "1" (or "true") to disable Xvfb entirely and use an existing (visible) X server.
no_xvfb = os.environ.get("NO_XVFB", "0").lower() in ("1", "true", "yes")

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info("Starting Google Meet recorder bot on WSL...")

# Ensure the output directory exists
os.makedirs(os.path.dirname(record_path), exist_ok=True)

# Parse screen resolution
try:
    width, height = map(int, screen_res.split('x'))
except Exception as e:
    logger.warning("Invalid SCREEN_RESOLUTION format. Falling back to 1280x720.")
    width, height = 1280, 720
try:
    depth = int(screen_depth)
except:
    depth = 24

# --- Start Xvfb only if NO_XVFB is not set ---
xvfb_proc = None
if not no_xvfb:
    display_env = f":{display_num}"
    xvfb_cmd = ["Xvfb", display_env, "-screen", "0", f"{width}x{height}x{depth}", "-ac"]
    try:
        logger.info(f"Launching Xvfb on display {display_env} with resolution {width}x{height}x{depth}...")
        xvfb_proc = subprocess.Popen(xvfb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(1)  # Allow Xvfb to initialize
        if xvfb_proc.poll() is not None:
            error_output = xvfb_proc.stderr.read().decode()
            logger.error(f"Xvfb failed to start. Error: {error_output.strip()}")
            logger.warning("Proceeding without Xvfb. Chrome will use the existing display.")
        else:
            os.environ["DISPLAY"] = display_env  # Set DISPLAY for child processes
            logger.info(f"Xvfb started on display {display_env}.")
    except FileNotFoundError:
        logger.error("Xvfb not installed or not found. Proceeding without Xvfb.")
else:
    logger.info("NO_XVFB is set; skipping Xvfb startup.")
    # Do not override DISPLAY so that an existing display (e.g., WSLg) is used.

# --- Start PulseAudio (for audio capture) ---
pulse_server = os.environ.get("PULSE_SERVER")
if pulse_server:
    logger.info(f"Using external PulseAudio server at {pulse_server}.")
else:
    try:
        subprocess.run(["pulseaudio", "--check"], check=True)
        logger.info("PulseAudio is already running.")
    except subprocess.CalledProcessError:
        try:
            subprocess.run(["pulseaudio", "--start"], check=True)
            logger.info("PulseAudio daemon started.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start PulseAudio: {e}")

# --- Launch undetected Chrome via Selenium ---
options = uc.ChromeOptions()
if chrome_path:
    options.binary_location = chrome_path

options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--no-first-run")
options.add_argument("--disable-sync")
options.add_argument("--disable-popup-blocking")
options.add_argument(f"--user-data-dir={user_data_dir}")
if not show_browser:
    # Only add headless flag if SHOW_BROWSER is false.
    options.add_argument("--headless")
    options.add_argument("--remote-debugging-port=9222")
options.add_argument("--use-fake-ui-for-media-stream")
options.add_argument("--use-fake-device-for-media-stream")
options.add_argument("--autoplay-policy=no-user-gesture-required")
options.add_argument(f"--window-size={width},{height}")

try:
    logger.info("Starting undetected Chrome WebDriver...")
    driver = uc.Chrome(options=options)
except WebDriverException as e:
    logger.error(f"Failed to start undetected Chrome WebDriver: {e}")
    if xvfb_proc:
        xvfb_proc.kill()
    raise

logger.info(f"Navigating to Google Meet link: {meet_link}")
driver.get(meet_link)
handle_popups(driver, logger=logger, timeout=3)

# --- Handle guest join (enter name) if prompted ---
try:
    name_input = WebDriverWait(driver, 10).until(
        lambda d: d.find_element(By.XPATH, '//input[@aria-label="Your name"]')
    )
    logger.info("Google Meet is asking for a name; entering display name...")
    name_input.clear()
    name_input.send_keys(display_name)
    logger.info(f"Entered name: {display_name}")
except Exception:
    logger.info("No guest name prompt detected; you may already be logged in.")

# --- Click join button ---
join_button_xpath = '//button[.//span[contains(text(), "Join now") or contains(text(), "Ask to join")]]'
try:
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, join_button_xpath)))
    join_button = driver.find_element(By.XPATH, join_button_xpath)
    join_text = join_button.text
    join_button.click()
    logger.info(f"Clicked \"{join_text}\" to join the meeting.")
except Exception as e:
    logger.error(f"Failed to click the join button: {e}")
    driver.quit()
    if xvfb_proc:
        xvfb_proc.kill()
    raise

logger.info("Joined meeting (or waiting for host approval). Starting recording...")
threading.Thread(target=periodic_popup_handler, args=(driver, logger), daemon=True).start()

# --- Start FFmpeg recording (video + audio) ---
ffmpeg_process = None
# If using an external display, use the current $DISPLAY. Otherwise, use Xvfb's display.
display_used = os.environ.get("DISPLAY", f":{display_num}")
if "headless" in options.arguments:
    # In headless mode, record audio only.
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-nostats",
        "-f", "pulse", "-i", "default",
        "-c:a", "aac", "-b:a", "128k",
        record_path.replace(".mp4", "_audio.mp4")
    ]
    logger.warning("Headless mode active; recording only audio.")
else:
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-nostats",
        "-f", "x11grab",
        "-video_size", f"{width}x{height}",
        "-i", f"{display_used}.0",
        "-f", "pulse",
        "-i", "default",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "25",
        record_path
    ]
try:
    logger.info("Launching FFmpeg for screen and audio recording...")
    ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    logger.info(f"FFmpeg started with PID {ffmpeg_process.pid}")
except Exception as e:
    logger.error(f"Failed to start FFmpeg: {e}")
    driver.quit()
    if xvfb_proc:
        xvfb_proc.kill()
    raise

logger.info("Recording in progress. Press Ctrl+C to stop.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Interrupt received, stopping recording...")
finally:
    if ffmpeg_process:
        try:
            ffmpeg_process.communicate(input=b"q", timeout=5)
            logger.info("FFmpeg stopped gracefully.")
        except Exception as e:
            logger.warning(f"FFmpeg did not stop gracefully: {e}")
            ffmpeg_process.kill()
    if driver:
        driver.quit()
        logger.info("Chrome WebDriver closed.")
    if xvfb_proc:
        xvfb_proc.kill()
        logger.info("Xvfb process terminated.")
