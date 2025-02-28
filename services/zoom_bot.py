# services/zoom_bot.py
import time
import os
import logging
import base64
import json
import undetected_chromedriver as uc  # Import undetected-chromedriver
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from utils import session_store

# Additional import for headless recording functionality
from pyvirtualdisplay import Display
import subprocess

logger = logging.getLogger(__name__)

# JavaScript for injecting MediaRecorder functionality
MEDIA_RECORDER_SCRIPT = """
// MediaRecorder functionality for Zoom meetings
window.mediaRecorder = null;
window.recordedChunks = [];

window.startMeetingRecording = async function() {
    try {
        // Wait for video elements to be present
        console.log("Waiting for video elements to initialize...");
        await new Promise(resolve => setTimeout(resolve, 5000));
        
        const videoElements = document.querySelectorAll('video');
        if (videoElements.length === 0) {
            console.error("No video elements found to record");
            return false;
        }
        
        console.log(`Found ${videoElements.length} video elements`);
        
        // Create a canvas that combines all video elements
        const canvas = document.createElement('canvas');
        canvas.width = 1280;
        canvas.height = 720;
        const ctx = canvas.getContext('2d');
        
        // Combine audio streams from all video elements
        const audioContext = new AudioContext();
        const audioDestination = audioContext.createMediaStreamDestination();
        
        videoElements.forEach(video => {
            if (video.srcObject) {
                video.srcObject.getAudioTracks().forEach(track => {
                    const source = audioContext.createMediaStreamSource(new MediaStream([track]));
                    source.connect(audioDestination);
                });
            }
        });
        
        // Function to draw videos to canvas
        function drawVideosToCanvas() {
            ctx.fillStyle = 'black';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            
            const videoCount = videoElements.length;
            if (videoCount === 1) {
                // Just one video, display it full size
                ctx.drawImage(videoElements[0], 0, 0, canvas.width, canvas.height);
            } else {
                // Grid layout for multiple videos
                const cols = Math.ceil(Math.sqrt(videoCount));
                const rows = Math.ceil(videoCount / cols);
                const width = canvas.width / cols;
                const height = canvas.height / rows;
                
                videoElements.forEach((video, i) => {
                    const x = (i % cols) * width;
                    const y = Math.floor(i / cols) * height;
                    ctx.drawImage(video, x, y, width, height);
                });
            }
            
            if (window.mediaRecorder && window.mediaRecorder.state === 'recording') {
                requestAnimationFrame(drawVideosToCanvas);
            }
        }
        
        // Create a composite media stream
        const canvasStream = canvas.captureStream(30);
        audioDestination.stream.getAudioTracks().forEach(track => {
            canvasStream.addTrack(track);
        });
        
        // Create and start the MediaRecorder
        window.recordedChunks = [];
        window.mediaRecorder = new MediaRecorder(canvasStream, { mimeType: 'video/webm; codecs=vp9,opus' });
        
        window.mediaRecorder.ondataavailable = event => {
            if (event.data.size > 0) {
                window.recordedChunks.push(event.data);
            }
        };
        
        window.mediaRecorder.onstop = () => {
            console.log("Recording stopped, preparing data...");
            window.recordingComplete = true;
        };
        
        window.mediaRecorder.start(1000); // Collect data every second
        requestAnimationFrame(drawVideosToCanvas);
        console.log("Meeting recording started successfully");
        return true;
    } catch (error) {
        console.error("Error starting recording:", error);
        return false;
    }
};

window.stopMeetingRecording = function() {
    return new Promise((resolve, reject) => {
        if (!window.mediaRecorder) {
            reject("No recording in progress");
            return;
        }
        
        window.recordingComplete = false;
        window.mediaRecorder.stop();
        
        // Wait for recording to complete processing
        const checkCompletion = setInterval(() => {
            if (window.recordingComplete) {
                clearInterval(checkCompletion);
                
                try {
                    const blob = new Blob(window.recordedChunks, { type: 'video/webm' });
                    resolve(blob);
                } catch (error) {
                    reject("Error creating recording blob: " + error);
                }
            }
        }, 100);
        
        // Timeout after 10 seconds
        setTimeout(() => {
            if (!window.recordingComplete) {
                clearInterval(checkCompletion);
                reject("Timed out waiting for recording to complete");
            }
        }, 10000);
    });
};

window.getRecordedData = function() {
    return new Promise((resolve, reject) => {
        if (!window.recordedChunks || window.recordedChunks.length === 0) {
            reject("No recorded data available");
            return;
        }
        
        try {
            const blob = new Blob(window.recordedChunks, { type: 'video/webm' });
            const reader = new FileReader();
            
            reader.onload = () => {
                resolve(reader.result);
            };
            
            reader.onerror = () => {
                reject("Error reading recorded data");
            };
            
            reader.readAsDataURL(blob);
        } catch (error) {
            reject("Error processing recorded data: " + error);
        }
    });
};
"""

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
    # If you plan to capture media, consider removing the headless mode.
    # options.add_argument("--headless")
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.binary_location = "/usr/bin/google-chrome"  # Adjust path if needed

    try:
        driver = uc.Chrome(options=options)
        logger.info("Undetected Chrome driver started successfully for Zoom.")
        # Increase script timeout for async operations (e.g. stopping recording)
        driver.set_script_timeout(60)
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
        return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))
    except Exception:
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
    Once the meeting page loads, injects JavaScript that polls for a composite media stream,
    starts recording when available, and exposes functions to stop recording.
    Updates the session status accordingly.
    """
    meeting_url = convert_zoom_url(meeting_url)
    
    logger.info(f"Starting Zoom session for {meeting_url} with session_id: {session_id}")
    try:
        user_data_dir = f"/tmp/chrome_user_data_{session_id}"
        os.makedirs(user_data_dir, exist_ok=True)
        
        driver = get_chrome_driver(user_data_dir)
        session = session_store.get_session(session_id)
        if session is not None:
            session["driver"] = driver
        
        driver.get(meeting_url)
        logger.info(f"Navigated to Zoom URL: {meeting_url}")
        time.sleep(5)
        
        try:
            name_input = find_element_in_frames(driver, By.ID, "input-for-name", timeout=20)
            name_input.clear()
            name_input.send_keys("Oracia")
            
            join_button = find_element_in_frames(driver, By.XPATH, "//button[text()='Join']", timeout=20)
            join_button.click()
            logger.info("Successfully filled in name 'Oracia' and clicked 'Join'.")
        except Exception as e:
            logger.exception(f"Could not fill in name or click 'Join': {e}")
        
        start_headless_recording(meeting_url, session_id, "/home/arnav/media-recorder/meeting_recording.webm")
        driver.execute_script("window.startMeetingRecording();")
        logger.info("Started recording the meeting via MediaRecorder API.")
        
        if session is not None:
            session["status"] = "joined"
            logger.info(f"Session {session_id} successfully joined Zoom meeting and started recording.")
    
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

def stop_recording_and_save(session_id: str, output_file: str):
    """
    Stops the recording by calling the injected JavaScript function.
    Retrieves the recorded data (a base64 data URL), decodes it,
    and saves it to the specified output file.
    If no recording is in progress, a warning is logged and the function exits gracefully.
    """
    session = session_store.get_session(session_id)
  

    try:
        stop_headless_recording(session_id)
        logger.info(f"Recording Stopped for session {session_id}.")
    except TimeoutException as te:
        logger.error(f"Script timeout during recording stop: {te}")
        raise
    except Exception as e:
        logger.exception(f"Failed to stop recording and save file: {str(e)}")
        raise

def leave_meeting(session_id: str):
    """
    Leaves a Zoom meeting by stopping the recording and then (optionally) closing the browser session.
    """
    logger.info(f"Attempting to leave Zoom session: {session_id}")
    session = session_store.get_session(session_id)
    
    output_filepath = "/home/arnav/media-recorder/meeting_recording.webm"
    try:
        stop_recording_and_save(session_id, output_filepath)
    except Exception as e:
        logger.error(f"Error during recording stop/save: {e}")
    
    # Uncomment below to close the browser session if needed.
    # if session and session.get("driver"):
    #     try:
    #         session["driver"].quit()
    #         logger.info(f"Session {session_id} closed successfully.")
    #     except Exception as e:
    #         logger.exception(f"Error closing Zoom session {session_id}: {str(e)}")


# ===================== BEGIN HEADLESS RECORDING CODE =====================
#
# This additional code enables a headless recording approach that uses:
#   - Xvfb (via pyvirtualdisplay) to create a virtual display.
#   - PulseAudio to create a virtual audio sink.
#   - ffmpeg to record the video from the virtual display and audio from the sink.
#

class VirtualDisplayManager:
    """Manages a headless virtual display using Xvfb (via pyvirtualdisplay)."""
    def __init__(self, resolution=(1920, 1080), fps=30):
        self.resolution = resolution
        self.fps = fps
        self.display = None

    def start(self):
        self.display = Display(visible=0, size=self.resolution)
        self.display.start()
        # Update the DISPLAY environment variable for child processes.
        os.environ["DISPLAY"] = f":{self.display.new_display_var or self.display.display}"
        logger.info(f"Virtual display started on DISPLAY={os.environ['DISPLAY']}")

    def stop(self):
        if self.display:
            self.display.stop()
            logger.info("Virtual display stopped.")

class PulseAudioManager:
    """
    Sets up a PulseAudio virtual sink so that browser audio is routed to an isolated sink.
    """
    def __init__(self, sink_name="virtual_sink"):
        self.sink_name = sink_name
        self.module_id = None

    def start(self):
        command = ["pactl", "load-module", "module-null-sink", f"sink_name={self.sink_name}"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error("Failed to load PulseAudio null sink: " + result.stderr)
            raise Exception("Failed to load PulseAudio null sink")
        self.module_id = result.stdout.strip()
        os.environ["PULSE_SINK"] = self.sink_name
        logger.info(f"PulseAudio virtual sink '{self.sink_name}' started with module ID {self.module_id}.")

    def stop(self):
        if self.module_id:
            command = ["pactl", "unload-module", self.module_id]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                logger.error("Failed to unload PulseAudio null sink: " + result.stderr)
            else:
                logger.info(f"PulseAudio virtual sink '{self.sink_name}' stopped.")
            self.module_id = None

class FFMpegRecorder:
    """
    Manages an ffmpeg process to capture video from the X11 display and audio from the PulseAudio sink.
    """
    def __init__(self, output_file, resolution=(1920, 1080), fps=30, audio_source="virtual_sink.monitor"):
        self.output_file = output_file
        self.resolution = resolution
        self.fps = fps
        self.audio_source = audio_source
        self.process = None

    def start(self):
        display = os.environ.get("DISPLAY", ":0")
        command = [
            "ffmpeg",
            "-y",  # Overwrite output file if exists
            "-video_size", f"{self.resolution[0]}x{self.resolution[1]}",
            "-framerate", str(self.fps),
            "-f", "x11grab",
            "-i", display,
            "-f", "pulse",
            "-i", self.audio_source,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-copyts",  # Copy timestamps for A/V sync
            self.output_file
        ]
        logger.info("Starting ffmpeg with command: " + " ".join(command))
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("ffmpeg recording started.")

    def stop(self):
        if self.process:
            logger.info("Stopping ffmpeg recording...")
            self.process.terminate()
            try:
                stdout, stderr = self.process.communicate(timeout=10)
                logger.info("ffmpeg terminated. Output:\n" +
                            stdout.decode('utf-8') + "\n" + stderr.decode('utf-8'))
            except subprocess.TimeoutExpired:
                logger.error("ffmpeg did not terminate in time; killing process.")
                self.process.kill()
            self.process = None

class HeadlessMeetingRecordingSession:
    """
    Encapsulates a headless recording session that:
      - Starts a virtual display and PulseAudio virtual sink.
      - Launches a browser session (using undetected_chromedriver) inside the virtual display.
      - Begins recording using ffmpeg.
    """
    def __init__(self, meeting_url, session_id, output_file,
                 resolution=(1920, 1080), fps=30, sink_name="virtual_sink"):
        self.meeting_url = meeting_url
        self.session_id = session_id
        self.output_file = output_file
        self.resolution = resolution
        self.fps = fps

        self.display_manager = VirtualDisplayManager(resolution=resolution, fps=fps)
        self.audio_manager = PulseAudioManager(sink_name=sink_name)
        self.recorder = FFMpegRecorder(output_file, resolution=resolution, fps=fps,
                                       audio_source=f"{sink_name}.monitor")
        self.driver = None

    def start(self):
        logger.info("Starting headless meeting recording session.")
        self.display_manager.start()
        self.audio_manager.start()

        # Launch the browser session inside the virtual display.
        user_data_dir = f"/tmp/chrome_user_data_{self.session_id}_headless"
        os.makedirs(user_data_dir, exist_ok=True)
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"--user-data-dir={user_data_dir}")
        # Do not use headless mode to ensure media capture.
        options.binary_location = "/usr/bin/google-chrome"  # Adjust if needed

        try:
            self.driver = uc.Chrome(options=options)
        except Exception as e:
            logger.exception("Failed to start Chrome driver in headless session: " + str(e))
            raise

        logger.info("Browser session (headless) started; navigating to meeting URL.")
        self.driver.get(self.meeting_url)
        time.sleep(5)  # Allow page to load

        # Start recording using ffmpeg.
        self.recorder.start()

    def stop(self):
        logger.info("Stopping headless meeting recording session.")
        self.recorder.stop()
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Browser session (headless) closed.")
            except Exception as e:
                logger.error("Error closing headless browser session: " + str(e))
        self.audio_manager.stop()
        self.display_manager.stop()
        logger.info("Headless meeting recording session stopped.")

def start_headless_recording(meeting_url: str, session_id: str, output_file: str):
    """
    Initializes and starts a headless meeting recording session.
    Stores the session object in the session_store under 'headless_recorder'.
    """
    recorder_session = HeadlessMeetingRecordingSession(meeting_url, session_id, output_file)
    session = session_store.get_session(session_id) or {}
    session["headless_recorder"] = recorder_session
    # If session_store supports saving, do so here.
    recorder_session.start()
    logger.info(f"Headless recording session started for session {session_id}.")

def stop_headless_recording(session_id: str):
    """
    Stops the headless meeting recording session if one is active.
    """
    session = session_store.get_session(session_id)
    if session and "headless_recorder" in session:
        try:
            session["headless_recorder"].stop()
            logger.info(f"Headless recording session stopped for session {session_id}.")
        except Exception as e:
            logger.error("Error stopping headless recording: " + str(e))
    else:
        logger.warning("No headless recording session found for session " + session_id)

# ====================== END HEADLESS RECORDING CODE ======================
