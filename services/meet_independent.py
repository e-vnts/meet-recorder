import os
import time
import logging
import subprocess
import threading
import sys
import requests  # Add this import for HTTP requests
import psutil

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# --- New imports for HTTP endpoint ---
from flask import Flask, request, jsonify

# --- Global variable for cleanup ---
already_stopped = False

# --- Define cleanup function before its usage in the HTTP endpoint ---
def stopScript():
    """
    Cleanup function to stop FFmpeg, close Chrome, and kill Xvfb.
    This function is called when a stop signal is received.
    """
    global already_stopped
    if already_stopped:
        return
    already_stopped = True
    logging.info("Executing stopScript cleanup...")
    current_directory = os.getcwd()
    logging.info("current_directory" + current_directory)
    if ffmpeg_process:
        try:
            try:
                ffmpeg_process.communicate(input=b"q", timeout=5)
                logging.info("FFmpeg stopped gracefully.")
            except Exception as e:
                logging.warning(f"FFmpeg did not stop gracefully: {e}")
                ffmpeg_process.kill()
            logging.info("FFmpeg stopped gracefully in stopScript.")
            
            # After successful recording completion, upload the video
            try:
                # Get the upload server URL from environment or use a default
                upload_server_url = "https://rw.debatesacademy.com"
                session_id = os.environ.get("SESSION_ID", "default-session")
                
                logging.info(f"Uploading recording to {upload_server_url} with session ID: {session_id}")
                
                # Step 1: Get a signed URL for upload
                response = requests.post(
                    f"{upload_server_url}/recording-worker/record/upload-video",
                    json={"sessionId":session_id}
                    
                )
                response.raise_for_status()  # Raise an exception for HTTP errors
                
                upload_data = response.json()
                signed_url = upload_data.get("signedUrl")
                
                logging.info(f"Received signed URL {signed_url}")
                
                # Step 2: Upload the video file using the signed URL
                with open(record_path, "rb") as video_file:
                    video_data = video_file.read()
                    upload_response = requests.put(
                        signed_url,
                        data=video_data,
                        headers={"Content-Type": "video/mp4"}
                    )
                    upload_response.raise_for_status()
                
                logging.info(f"Successfully uploaded recording to {upload_server_url}")
                
            except requests.exceptions.RequestException as e:
                logging.error(f"Error during upload: {e}")
            except IOError as e:
                logging.error(f"Error reading video file: {e}")
            except Exception as e:
                logging.error(f"Unexpected error during upload: {e}")
                
        except Exception as e:
            logging.warning(f"FFmpeg did not stop gracefully in stopScript: {e}")
            ffmpeg_process.kill()
    
    # Continue with the original cleanup
    if driver:
        driver.quit()
        logging.info("Chrome WebDriver closed in stopScript.")
    if xvfb_proc:
        xvfb_proc.kill()
        logging.info("Xvfb process terminated in stopScript.")

# --- Flask app and termination event for graceful shutdown ---
app = Flask(__name__)
stop_event = threading.Event()

@app.route('/internal_stop', methods=['POST'])
def internal_stop():
    global already_stopped
    logging.info("Received internal stop request via HTTP endpoint.")
    if not already_stopped:
        stopScript()  # Call the cleanup function
    stop_event.set()  # Signal main loop to exit
    return jsonify({"message": "Stop signal processed."}), 200

def run_flask():
    # Run the Flask app; debug is off and use_reloader is disabled for thread safety.
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)

# --- Existing configuration and setup ---
def handle_popups(driver, logger=None, timeout=3):
    """
    Looks for common pop-ups or info boxes in Google Meet
    and dismisses them if present. Adjust XPaths or text as needed.
    """
    if logger is None:
        import logging
        logger = logging.getLogger(__name__)

    popup_selectors = [
        ('//span[text()="Got it"]', 'Got it'),
        ('//span[text()="Continue without microphone and camera"]', 'Continue without microphone and camera'),
        ('//span[text()="Continue without microphone"]', 'Continue without microphone'),
    ]

    for xpath, desc in popup_selectors:
        try:
            if WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            ):
                elem = driver.find_element(By.XPATH, xpath)
                elem.click()
                logger.info(f"Dismissed/Clicked '{desc}' popup.")
                time.sleep(0.5)
        except (NoSuchElementException, TimeoutException):
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
display_name = os.environ.get("DISPLAY_NAME", "Oracia")

chrome_path = os.environ.get("CHROME_BINARY")
user_data_dir = os.environ.get("CHROME_USER_DATA_DIR", "/tmp/meet_bot_profile")

show_browser = True
no_xvfb = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info("Starting Google Meet recorder bot...")

os.makedirs(os.path.dirname(record_path), exist_ok=True)

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
        time.sleep(1)
        if xvfb_proc.poll() is not None:
            error_output = xvfb_proc.stderr.read().decode()
            logger.error(f"Xvfb failed to start. Error: {error_output.strip()}")
            logger.warning("Proceeding without Xvfb. Chrome will use the existing display.")
        else:
            os.environ["DISPLAY"] = display_env
            logger.info(f"Xvfb started on display {display_env}.")
    except FileNotFoundError:
        logger.error("Xvfb not installed or not found. Proceeding without Xvfb.")
else:
    logger.info("NO_XVFB is set; skipping Xvfb startup.")

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

# --- Start Flask server in a background thread ---
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()
logger.info("Flask endpoint for internal stop is running on port 5001.")

# --- Start FFmpeg recording (video + audio) ---
ffmpeg_process = None
display_used = os.environ.get("DISPLAY", f":{display_num}")
os.makedirs(os.path.dirname(record_path), exist_ok=True)


if "headless" in options.arguments:
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-nostats",
        "-f", "pulse", "-i", "default",
        "-c:a", "aac", "-b:a", "128k", record_path.replace(".mp4", "_audio.mp4")
    ]
    logger.warning("Headless mode active; recording only audio.")
else:
    if os.path.exists(record_path):
        logger.info("Record output file already exists.")
        # Check if any running ffmpeg process is using the record file.
        for proc in psutil.process_iter(attrs=["cmdline"]):
            cmdline = proc.info.get("cmdline", [])
            if cmdline and "ffmpeg" in cmdline[0] and record_path in ' '.join(cmdline):
                logger.info("The record output file is currently being recorded.")
                break
    else:
        # Create the file before recording
        with open(record_path, 'w') as f:
            pass
        logger.info("Created the record output file.")

# Now build the ffmpeg command.
ffmpeg_cmd = [
    "ffmpeg", "-y", "-nostats",
    "-f", "x11grab",
    "-video_size", f"{width}x{height}",
    "-i", f"{display_used}.0",
    "-f", "pulse",
    "-i", "default",
    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "128k",
    "-r", "25", record_path
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

logger.info("Recording in progress. Press Ctrl+C or send a POST request to /internal_stop to stop.")

# --- Main loop now checks for the stop event ---
try:
    while not stop_event.is_set():
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Keyboard interrupt received, stopping recording...")
    stop_event.set()
finally:
    if ffmpeg_process:
        try:
            ffmpeg_process.communicate(input=b"q", timeout=5)
            logging.info("FFmpeg stopped gracefully.")
        except Exception as e:
            logging.warning(f"FFmpeg did not stop gracefully: {e}")
            ffmpeg_process.kill()
    if driver:
        driver.quit()
        logger.info("Chrome WebDriver closed.")
    if xvfb_proc:
        xvfb_proc.kill()
        logger.info("Xvfb process terminated.")
