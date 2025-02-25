# services/zoom_bot.py
import time
import os
import logging
import base64
import undetected_chromedriver as uc  # Import undetected-chromedriver
from selenium.common.exceptions import WebDriverException, TimeoutException
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
        
        # Inject JavaScript for recording with enhanced polling and detailed logging.
        recording_js = """
        (function() {
            if (window.__meetingRecorderInitialized) return;
            window.__meetingRecorderInitialized = true;
            window.recordedChunks = [];
            window.mediaRecorder = null;
            
            // Poll for a composite element and a valid media stream with available tracks.
            function pollForStream(attempts) {
                attempts = attempts || 0;
                console.log("Polling for media stream, attempt: " + attempts);
                var compositeElem = document.getElementById('composite-stream') || document.querySelector('video');
                if (!compositeElem) {
                    console.error("Composite element not found on attempt: " + attempts);
                } else {
                    console.log("Composite element found: " + compositeElem.tagName);
                    var stream = compositeElem.captureStream();
                    if (!stream) {
                        console.warn("captureStream returned null on attempt: " + attempts);
                    } else {
                        var tracks = stream.getTracks();
                        console.log("Stream tracks found: " + (tracks.map(function(t){ return t.kind; }).join(', ')));
                        if (tracks.length === 0) {
                            console.warn("No media tracks available on composite element on attempt: " + attempts);
                        } else {
                            console.log("Media stream available with " + tracks.length + " track(s).");
                            return Promise.resolve(stream);
                        }
                    }
                }
                if (attempts < 30) { // Increase polling attempts if necessary
                    return new Promise(function(resolve, reject) {
                        setTimeout(function() {
                            pollForStream(attempts + 1).then(resolve).catch(reject);
                        }, 1000);
                    });
                } else {
                    return Promise.reject("No media stream available after polling.");
                }
            }
            
            // Start recording by polling until a valid media stream is found.
            function startRecording() {
                pollForStream(0).then(function(stream) {
                    var options = {mimeType: 'video/webm; codecs=vp9'};
                    try {
                        window.mediaRecorder = new MediaRecorder(stream, options);
                        console.log("MediaRecorder initialized with options.");
                    } catch (e) {
                        console.error("MediaRecorder initialization failed with options; trying without options.", e);
                        try {
                            window.mediaRecorder = new MediaRecorder(stream);
                            console.log("MediaRecorder initialized without options.");
                        } catch (err) {
                            console.error("MediaRecorder initialization failed without options.", err);
                            return;
                        }
                    }
                    window.mediaRecorder.ondataavailable = function(e) {
                        if (e.data && e.data.size > 0) {
                            window.recordedChunks.push(e.data);
                            console.log("Data available, size: " + e.data.size);
                        }
                    };
                    window.mediaRecorder.start(1000);
                    console.log("Recording started.");
                }).catch(function(error) {
                    console.error("Failed to get media stream: " + error);
                });
            }
            
            function pollAndStartRecording() {
                console.log("Polling and starting recording...");
                startRecording();
            }
            
            // Stop recording and process the recorded data.
            function stopRecording() {
                return new Promise(function(resolve, reject) {
                    if (!window.mediaRecorder) {
                        reject("No recording in progress.");
                        return;
                    }
                    window.mediaRecorder.onstop = function(e) {
                        console.log("MediaRecorder stopped, processing data...");
                        var blob = new Blob(window.recordedChunks, {type: 'video/webm'});
                        var reader = new FileReader();
                        reader.onload = function() {
                            console.log("Recording processed.");
                            resolve(reader.result);
                        };
                        reader.onerror = function(err) {
                            reject(err);
                        };
                        reader.readAsDataURL(blob);
                    };
                    window.mediaRecorder.stop();
                    console.log("Stop command issued to MediaRecorder.");
                });
            }
            
            window.startMeetingRecording = pollAndStartRecording;
            window.stopMeetingRecording = stopRecording;
        })();
        """
        driver.execute_script(recording_js)
        logger.info("Injected recording script into meeting page.")
        
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
    if not session or "driver" not in session:
        raise Exception("Session not found or driver not available")
    driver = session["driver"]

    try:
        driver.set_script_timeout(60)
        base64_data = driver.execute_async_script("""
            var callback = arguments[arguments.length - 1];
            window.stopMeetingRecording().then(function(result) {
                callback(result);
            }).catch(function(e) {
                callback({"error": e.toString()});
            });
        """)
        if isinstance(base64_data, dict) and "error" in base64_data:
            if "No recording in progress" in base64_data["error"]:
                logger.warning("No recording in progress. Skipping recording save.")
                return
            else:
                raise Exception("Error stopping recording: " + base64_data["error"])
        header, encoded = base64_data.split(",", 1)
        binary_data = base64.b64decode(encoded)
        with open(output_file, "wb") as f:
            f.write(binary_data)
        logger.info(f"Recording saved successfully to {output_file}")
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
