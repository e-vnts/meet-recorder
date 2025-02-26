from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import logging
import time
import os
import subprocess
import signal
import threading
import undetected_chromedriver as uc
import shutil
from utils import session_store
from pyvirtualdisplay import Display


# Additional import for headless recording functionality
from pyvirtualdisplay import Display

logger = logging.getLogger(__name__)

def convert_zoom_url(url):
    # Extract meeting id by finding '/j/' and taking the substring until the next '?'
    try:
        j_index = url.index("/j/")
        start = j_index + len("/j/")
        q_index = url.find("?", start)
        if q_index == -1:
            meeting_id = url[start:]
            logger.debug(f"Meeting ID extracted: {meeting_id}")
        else:
            meeting_id = url[start:q_index]
            logger.debug(f"Meeting ID extracted: {meeting_id}")
    except ValueError:
        logger.error("URL does not contain '/j/' in the expected format.")
        raise ValueError("URL does not contain '/j/' in the expected format.")

    # Extract the password by locating "pwd=" and taking the substring until the next '&' if present.
    pwd_marker = "pwd="
    pwd_index = url.find(pwd_marker)
    if (pwd_index == -1):
        logger.error("URL does not contain a 'pwd=' parameter.")
        raise ValueError("URL does not contain a 'pwd=' parameter.")
    pwd_start = pwd_index + len(pwd_marker)
    amp_index = url.find("&", pwd_start)
    if amp_index == -1:
        pwd = url[pwd_start:]
        logger.debug(f"Password extracted: {pwd}")
    else:
        pwd = url[pwd_start:amp_index]
        logger.debug(f"Password extracted: {pwd}")

    # Construct the new URL using string concatenation.
    new_url = "https://app.zoom.us/wc/" + meeting_id + "/join?fromPWA=1&pwd=" + pwd
    logger.debug(f"New Zoom URL constructed: {new_url}")
    return new_url

def get_chrome_driver(user_data_dir: str):
    """
    Creates and returns a Chrome WebDriver instance using undetected-chromedriver.
    The '--user-data-dir' argument ensures a separate browser profile per session.
    """
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.binary_location = "/usr/bin/google-chrome"  # Adjust path if needed
    options.add_argument("--use-fake-ui-for-media-stream")  # Auto-allow media permissions
    options.add_argument("--autoplay-policy=no-user-gesture-required")  # Allow autoplay
    logger.debug("Chrome options set.")

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
    logger.debug(f"Attempting to find element with locator: ({by}, {value})")
    try:
        element = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))
        logger.debug(f"Element found with locator: ({by}, {value})")
        return element
    except Exception:
        logger.debug(f"Element with locator ({by}, {value}) not found in default content. Searching iframes...")
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                element = WebDriverWait(driver, 5).until(EC.presence_of_element_located((by, value)))
                logger.debug(f"Element found in iframe with locator: ({by}, {value})")
                return element
            except Exception:
                driver.switch_to.default_content()
        logger.error(f"Element with locator ({by}, {value}) not found in any frame.")
        raise Exception(f"Element with locator ({by}, {value}) not found in any frame.")

def join_meeting(meeting_url: str, session_id: str):
    """
    Joins a Zoom meeting and starts a headless recording session.
    """
    logger.info(f"Attempting to join Zoom meeting with session_id: {session_id}")
    meeting_url = convert_zoom_url(meeting_url)
    
    logger.info(f"Starting Zoom session for {meeting_url} with session_id: {session_id}")
    try:
        user_data_dir = f"/tmp/chrome_user_data_{session_id}"
        os.makedirs(user_data_dir, exist_ok=True)
        logger.debug(f"Created user data directory: {user_data_dir}")
        
        # Use a consistent output filepath for both starting and stopping the recording.
        output_filepath = "/home/arnav/media-recorder/meeting_recording.webm"
        start_headless_recording(meeting_url, session_id, output_filepath)
        
        # Launch the browser within the virtual display
        driver = get_chrome_driver(user_data_dir)
        session = session_store.get_session(session_id)
        if session is not None:
            session["driver"] = driver
            session["status"] = "connecting"
            session_store.update_session(session_id, session)
            logger.debug(f"Session {session_id} updated with driver and status 'connecting'.")
        
        driver.get(meeting_url)
        logger.info(f"Navigated to Zoom URL: {meeting_url}")
        time.sleep(5)
        
        try:
            name_input = find_element_in_frames(driver, By.ID, "input-for-name", timeout=20)
            name_input.clear()
            name_input.send_keys("Oracia")
            logger.debug("Filled in name 'Oracia'.")
            
            join_button = find_element_in_frames(driver, By.XPATH, "//button[text()='Join']", timeout=20)
            join_button.click()
            logger.info("Successfully filled in name 'Oracia' and clicked 'Join'.")
        except Exception as e:
            logger.warning(f"Could not find or click join button: {e}")
        
        logger.info("Headless recording is now active")
        
        if session is not None:
            session["status"] = "recording"
            session_store.update_session(session_id, session)
            logger.debug(f"Session {session_id} updated with status 'recording'.")
    
    except WebDriverException as e:
        logger.exception(f"WebDriverException in Zoom session {session_id}: {str(e)}")
        session = session_store.get_session(session_id)
        if session is not None:
            session["status"] = "error"
            session["error"] = str(e)
            session_store.update_session(session_id, session)
            logger.debug(f"Session {session_id} updated with status 'error' and error message.")
    except Exception as e:
        logger.exception(f"Unexpected error in Zoom session {session_id}: {str(e)}")
        session = session_store.get_session(session_id)
        if session is not None:
            session["status"] = "error"
            session["error"] = str(e)
            session_store.update_session(session_id, session)
            logger.debug(f"Session {session_id} updated with status 'error' and error message.")

def stop_recording_and_save(session_id: str, output_file: str):
    """
    Stops the headless recording session.
    """
    logger.info(f"Attempting to stop recording and save for session: {session_id}")
    session = session_store.get_session(session_id)
    
    try:
        stop_headless_recording(session_id)
        logger.info(f"Recording stopped for session {session_id}. The output file should be located at: {output_file}")
        
        if session:
            session["status"] = "completed"
            session_store.update_session(session_id, session)
            logger.debug(f"Session {session_id} updated with status 'completed'.")
    except Exception as e:
        logger.exception(f"Failed to stop recording: {str(e)}")
        if session:
            session["status"] = "error"
            session["error"] = str(e)
            session_store.update_session(session_id, session)
            logger.debug(f"Session {session_id} updated with status 'error' and error message.")
        raise

def leave_meeting(session_id: str):
    """
    Leaves a Zoom meeting by stopping the headless recording and closing the browser session.
    """
    logger.info(f"Attempting to leave Zoom meeting with session_id: {session_id}")
    output_filepath = "/home/arnav/media-recorder/meeting_recording.webm"
    try:
        stop_recording_and_save(session_id, output_filepath)
    except Exception as e:
        logger.error(f"Error during recording stop/save: {e}")
    
    session = session_store.get_session(session_id)
    if session and session.get("driver"):
        try:
            session["driver"].quit()
            logger.info(f"Session {session_id} closed successfully.")
        except Exception as e:
            logger.exception(f"Error closing Zoom session {session_id}: {str(e)}")

# ===================== HEADLESS RECORDING CODE =====================



class VirtualDisplayManager:
    """Manages a virtual display using Xvfb or Xephyr (via pyvirtualdisplay)."""
    def __init__(self, resolution=(1920, 1080), fps=30, visible=True):
        self.resolution = resolution
        self.fps = fps
        self.visible = visible  # True for a visible display (Xephyr), False for headless (Xvfb)
        self.display = None
        logger.debug(f"VirtualDisplayManager initialized with resolution: {resolution}, fps: {fps}, visible: {visible}")

    def start(self):
        if self.visible:
            backend = "xvfb"
            logger.info("Using Xvfb backend for headless virtual display.")
            extra_args = []  # Do not use -unixsockdir for Xvfb. # Do not pass -unixsockdir because Xvfb in your environment doesn't support it.
        else:
            backend = "xvfb"
            logger.info("Using Xvfb backend for headless virtual display.")
            extra_args = []  # Do not use -unixsockdir for Xvfb.

        self.display = Display(backend=backend, visible=self.visible, size=self.resolution, extra_args=extra_args)
        self.display.start()
        os.environ["DISPLAY"] = f":{self.display.new_display_var or self.display.display}"
        logger.info(f"Virtual display started on DISPLAY={os.environ['DISPLAY']} with backend={backend} and extra_args={extra_args}")

    def stop(self):
        if self.display:
            self.display.stop()
            logger.info("Virtual display stopped")

class PulseAudioManager:
    """
    Sets up a PulseAudio virtual sink so that browser audio is routed to an isolated sink.
    """
    def __init__(self, sink_name="virtual_sink"):
        self.sink_name = sink_name
        self.module_id = None

    def start(self):
        command = ["pactl", "load-module", "module-null-sink", f"sink_name={self.sink_name}"]
        try:
            result = subprocess.check_output(command, text=True)
            self.module_id = result.strip()
            logger.info(f"PulseAudio virtual sink created with module ID: {self.module_id}")
            
            subprocess.run(["pactl", "set-default-sink", self.sink_name], check=True)
            logger.info(f"Set {self.sink_name} as default sink")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create PulseAudio virtual sink: {e}")
            return False

    def stop(self):
        if self.module_id:
            try:
                subprocess.run(["pactl", "unload-module", self.module_id], check=True)
                logger.info(f"PulseAudio module {self.module_id} unloaded")
                self.module_id = None
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to unload PulseAudio module: {e}")
                return False
        return True


class FFMpegRecorder:
    """
    Manages an ffmpeg process to capture video from the X11 display and audio from the PulseAudio sink.
    """
    def __init__(self, output_file, resolution=(1920, 1080), fps=30, audio_source="virtual_sink.monitor"):
        self.output_file = output_file
        self.resolution = f"{resolution[0]}x{resolution[1]}"
        self.fps = fps
        self.audio_source = audio_source
        self.process = None
        self.ffmpeg_thread = None

    def _log_ffmpeg_output(self):
        """Continuously logs ffmpeg stderr output."""
        for line in iter(self.process.stderr.readline, b''):
            if line:
                logger.info("FFmpeg: " + line.decode('utf-8').strip())
            else:
                break

    def start(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.output_file)), exist_ok=True)
        command = [
            "ffmpeg",
            "-y",  # Overwrite output files
            "-f", "x11grab",  # X11 display grabbing
            "-framerate", str(self.fps),
            "-video_size", self.resolution,
            "-i", os.environ.get("DISPLAY", ":0"),  # Input from X display
            "-f", "pulse",  # PulseAudio input
            "-i", self.audio_source,  # Audio source
            "-c:v", "libx264",  # Video codec
            "-preset", "ultrafast",
            "-c:a", "aac",  # Audio codec
            "-strict", "experimental",
            "-b:a", "192k",
            self.output_file
        ]
        
        logger.info(f"Starting FFmpeg recording with command: {' '.join(command)}")
        
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1
        )
        
        if self.process.poll() is not None:
            out, err = self.process.communicate()
            raise Exception(f"FFmpeg failed to start: {err.decode()}")
        
        # Start a thread to log ffmpeg output continuously.
        self.ffmpeg_thread = threading.Thread(target=self._log_ffmpeg_output, daemon=True)
        self.ffmpeg_thread.start()
        
        logger.info(f"FFmpeg recording started, saving to {self.output_file}")
        return True

    def stop(self):
        if self.process:
            logger.info("Stopping FFmpeg recording")
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
                logger.info("FFmpeg recording stopped successfully")
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg process didn't terminate gracefully, forcing termination")
                self.process.kill()
                self.process.wait()
            self.process = None
            return True
        return False


class HeadlessMeetingRecordingSession:
    """
    Encapsulates a recording session that:
      - Starts a virtual display and PulseAudio virtual sink.
      - Launches a browser session (using undetected-chromedriver) inside the virtual display.
      - Begins recording using ffmpeg.
    """
    def __init__(self, meeting_url, session_id, output_file,
                 resolution=(1920, 1080), fps=30, sink_name="virtual_sink", visible=True):
        self.meeting_url = meeting_url
        self.session_id = session_id
        self.output_file = output_file
        self.resolution = resolution
        self.fps = fps
        self.sink_name = sink_name
        self.visible = visible
        
        # Initialize components
        self.display_manager = VirtualDisplayManager(resolution=resolution, fps=fps, visible=visible)
        self.audio_manager = PulseAudioManager(sink_name=sink_name)
        self.recorder = FFMpegRecorder(
            output_file=output_file,
            resolution=resolution,
            fps=fps,
            audio_source=f"{sink_name}.monitor"
        )

    def start(self):
        logger.info("Starting headless meeting recording session...")
        # Always start a virtual display.
        self.display_manager.start()
        
        # Always configure PulseAudio virtual sink, even in debug mode.
        if not self.audio_manager.start():
            self.display_manager.stop()
            raise Exception("Failed to configure PulseAudio virtual sink")
        
        # Start recording
        if not self.recorder.start():
            self.audio_manager.stop()
            self.display_manager.stop()
            raise Exception("Failed to start FFmpeg recording")
        
        logger.info(f"Headless recording session started for {self.meeting_url}")
        return True

    def stop(self):
        logger.info("Stopping headless meeting recording session...")
        success = True
        
        try:
            if not self.recorder.stop():
                logger.warning("Failed to stop FFmpeg recorder")
                success = False
        except Exception as e:
            logger.error(f"Error stopping recorder: {e}")
            success = False
        
        try:
            if not self.audio_manager.stop():
                logger.warning("Failed to stop PulseAudio manager")
                success = False
        except Exception as e:
            logger.error(f"Error stopping audio manager: {e}")
            success = False
        
        try:
            self.display_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping display manager: {e}")
            success = False
        
        logger.info(f"Headless recording session {'successfully' if success else 'partially'} stopped")
        return success


def start_headless_recording(meeting_url: str, session_id: str, output_file: str, debug_mode=True):
    """
    Initializes and starts a meeting recording session.
    When debug_mode is True, the virtual display will be visible.
    """
    logger.info(f"Starting headless recording for session: {session_id}, debug_mode: {debug_mode}")
    recorder_session = HeadlessMeetingRecordingSession(
        meeting_url, 
        session_id, 
        output_file,
        visible=debug_mode
    )
    session = session_store.get_session(session_id) or {}
    session["headless_recorder"] = recorder_session
    session_store.update_session(session_id, session)
    recorder_session.start()
    logger.info(f"Recording session started for session {session_id} in {'debug' if debug_mode else 'headless'} mode.")

def stop_headless_recording(session_id: str):
    """
    Stops the headless meeting recording session if one is active.
    """
    logger.info(f"Attempting to stop headless recording for session: {session_id}")
    session = session_store.get_session(session_id)
    if session and "headless_recorder" in session:
        recorder = session["headless_recorder"]
        recorder.stop()
        logger.info(f"Headless recording stopped for session {session_id}.")
        return True
    else:
        logger.warning(f"No headless recorder found for session {session_id}.")
        return False
