import os
import time
import logging
import subprocess
import threading
import uuid
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from utils.session_store import get_session, update_session, add_session, remove_session
from utils.background_tasks import task_manager
from utils.display_manager import display_manager
from models.meeting import MeetingStatus

logger = logging.getLogger(__name__)

def handle_popups(driver, logger=None, timeout=3):
    """
    Looks for common pop-ups or info boxes in Google Meet
    and dismisses them if present.
    """
    if logger is None:
        import logging
        logger = logging.getLogger(__name__)
    
    # List of (XPATH, description) pairs for popups to dismiss
    popup_selectors = [
        # Example: "Got it" button
        ('//span[text()="Got it"]', 'Got it'),
        # Add other selectors as needed
    ]

    # Try each popup selector
    for xpath, desc in popup_selectors:
        try:
            elem = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            elem.click()
            logger.info(f"Dismissed '{desc}' popup.")
        except (NoSuchElementException, TimeoutException):
            pass
        except Exception as e:
            logger.warning(f"Could not dismiss '{desc}' popup: {e}")

def periodic_popup_handler(driver, session_id, logger):
    """Periodically check and handle popups"""
    while True:
        session_data = get_session(session_id)
        if not session_data or session_data.get('status') in [MeetingStatus.STOPPED, MeetingStatus.ERROR]:
            logger.info(f"Stopping popup handler for session {session_id}")
            break

        try:
            handle_popups(driver, logger=logger, timeout=2)
            time.sleep(5)  # check every 5 seconds
        except Exception as e:
            logger.warning(f"Popup handler encountered an error: {e}")
            break

class MeetService:
    """Service for managing Google Meet recording sessions"""
    
    @staticmethod
    def start_meeting(
        meet_link: str, 
        display_name: str = "Oracia",
        record_path: str = "recordings/output.mp4", 
        screen_resolution: str = "1280x720",
        show_browser: bool = False,
        chrome_path: str = None,
        user_data_dir: str = "/tmp/meet_bot_profile"
    ) -> str:
        """Start a new meeting recording session"""
        
        # Generate unique session ID and create directory for this session
        session_id = str(uuid.uuid4())
        session_dir = os.path.join("recordings", session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Update the record path to be session-specific
        record_filename = os.path.basename(record_path)
        record_path = os.path.join(session_dir, record_filename)
        
        # Create initial session data
        session_data = {
            'meet_link': meet_link,
            'display_name': display_name,
            'record_path': record_path,
            'screen_resolution': screen_resolution,
            'show_browser': show_browser,
            'start_time': time.time(),
            'driver': None,
            'ffmpeg_process': None,
            'status': MeetingStatus.PENDING,
            'error': None
        }
        
        # Add session to store
        add_session(session_id, session_data)
        
        # Start the meeting in a background task
        task_manager.start_task(
            session_id, 
            MeetService._run_meeting_session,
            session_id=session_id,
            meet_link=meet_link, 
            display_name=display_name,
            record_path=record_path, 
            screen_resolution=screen_resolution,
            show_browser=show_browser,
            chrome_path=chrome_path,
            user_data_dir=user_data_dir
        )
        
        return session_id
    
    @staticmethod
    def _run_meeting_session(
        session_id: str,
        meet_link: str, 
        display_name: str,
        record_path: str, 
        screen_resolution: str,
        show_browser: bool,
        chrome_path: str = None,
        user_data_dir: str = None
    ):
        """Internal method to run a meeting session as a background task"""
        
        try:
            # Update session status to joining
            session_data = get_session(session_id)
            session_data['status'] = MeetingStatus.JOINING
            update_session(session_id, session_data)
            
            # Parse screen resolution
            try:
                width, height = map(int, screen_resolution.split('x'))
            except Exception:
                logger.warning(f"Invalid screen resolution format: {screen_resolution}. Falling back to 1280x720.")
                width, height = 1280, 720
            
            # Allocate a display for this session
            display_env = display_manager.allocate_display(session_id, width, height)
            if not display_env:
                raise RuntimeError("Failed to allocate display for the session")
            
            session_data['display'] = display_env
            update_session(session_id, session_data)
            
            # Set environment variables for this session
            os.environ["DISPLAY"] = display_env
            
            # Start PulseAudio if needed
            try:
                subprocess.run(["pulseaudio", "--check"], check=True)
                logger.info("PulseAudio is already running.")
            except subprocess.CalledProcessError:
                try:
                    subprocess.run(["pulseaudio", "--start"], check=True)
                    logger.info("PulseAudio daemon started.")
                except Exception as e:
                    logger.error(f"Failed to start PulseAudio: {e}")
            
            # Launch Chrome driver
            options = uc.ChromeOptions()
            if chrome_path:
                options.binary_location = chrome_path

            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-first-run")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-popup-blocking")
            if user_data_dir:
                options.add_argument(f"--user-data-dir={user_data_dir}")
            if not show_browser:
                options.add_argument("--headless")
                options.add_argument("--remote-debugging-port=9222")
            options.add_argument("--use-fake-ui-for-media-stream")
            options.add_argument("--use-fake-device-for-media-stream")
            options.add_argument("--autoplay-policy=no-user-gesture-required")
            options.add_argument(f"--window-size={width},{height}")

            driver = uc.Chrome(options=options)
            session_data['driver'] = driver
            update_session(session_id, session_data)
            
            logger.info(f"Navigating to Google Meet link: {meet_link}")
            driver.get(meet_link)
            handle_popups(driver, logger=logger, timeout=3)
            
            # Handle guest join if prompted
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
            
            # Click join button
            join_button_xpath = '//button[.//span[contains(text(), "Join now") or contains(text(), "Ask to join")]]'
            try:
                WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, join_button_xpath)))
                join_button = driver.find_element(By.XPATH, join_button_xpath)
                join_text = join_button.text
                join_button.click()
                logger.info(f"Clicked \"{join_text}\" to join the meeting.")
            except Exception as e:
                logger.error(f"Failed to click the join button: {e}")
                raise
            
            # Start periodic popup handler
            threading.Thread(
                target=periodic_popup_handler, 
                args=(driver, session_id, logger), 
                daemon=True
            ).start()
            
            # Start FFmpeg recording
            display_used = display_env
            if "headless" in options.arguments:
                # In headless mode, record audio only
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
                
            logger.info("Launching FFmpeg for recording...")
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd, 
                stdin=subprocess.PIPE, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
            logger.info(f"FFmpeg started with PID {ffmpeg_process.pid}")
            
            session_data['ffmpeg_process'] = ffmpeg_process
            session_data['status'] = MeetingStatus.RECORDING
            update_session(session_id, session_data)
            
            # Monitor the session status for stop requests
            while True:
                updated_session = get_session(session_id)
                if not updated_session:
                    logger.warning(f"Session {session_id} not found. Stopping recording.")
                    break
                
                if updated_session.get('status') == MeetingStatus.STOPPED:
                    logger.info(f"Stop requested for session {session_id}")
                    break
                
                # Check if ffmpeg is still running
                if ffmpeg_process.poll() is not None:
                    logger.warning(f"FFmpeg process terminated unexpectedly with code {ffmpeg_process.poll()}")
                    break
                
                time.sleep(5)
            
            return {"status": "completed", "recording_path": record_path}
            
        except Exception as e:
            logger.exception(f"Error in meeting session {session_id}: {str(e)}")
            session_data = get_session(session_id) or {}
            session_data['status'] = MeetingStatus.ERROR
            session_data['error'] = str(e)
            update_session(session_id, session_data)
            return {"status": "error", "error": str(e)}
        
        finally:
            # Cleanup resources
            session_data = get_session(session_id)
            if session_data:
                try:
                    # Stop ffmpeg process if running
                    ffmpeg_process = session_data.get('ffmpeg_process')
                    if ffmpeg_process and ffmpeg_process.poll() is None:
                        try:
                            ffmpeg_process.communicate(input=b"q", timeout=5)
                            logger.info(f"FFmpeg stopped gracefully for session {session_id}.")
                        except Exception:
                            ffmpeg_process.kill()
                            logger.warning(f"FFmpeg killed for session {session_id}.")
                    
                    # Quit the driver
                    driver = session_data.get('driver')
                    if driver:
                        driver.quit()
                        logger.info(f"Chrome WebDriver closed for session {session_id}.")
                    
                    # Release the display
                    display_manager.release_display(session_id)
                    
                    if session_data.get('status') != MeetingStatus.ERROR:
                        session_data['status'] = MeetingStatus.STOPPED
                    
                    session_data['driver'] = None
                    session_data['ffmpeg_process'] = None
                    session_data['end_time'] = time.time()
                    update_session(session_id, session_data)
                    
                except Exception as e:
                    logger.exception(f"Error during cleanup for session {session_id}: {str(e)}")
    
    @staticmethod
    def stop_meeting(session_id: str) -> bool:
        """Stop a running meeting recording session"""
        session_data = get_session(session_id)
        if not session_data:
            return False
        
        if session_data.get('status') == MeetingStatus.RECORDING:
            session_data['status'] = MeetingStatus.STOPPED
            update_session(session_id, session_data)
            return True
        
        return False
    
    @staticmethod
    def get_meeting_status(session_id: str) -> dict:
        """Get the current status of a meeting session"""
        session_data = get_session(session_id)
        if not session_data:
            return {"status": "not_found"}
        
        # Get task status
        task_status = task_manager.get_task_status(session_id)
        
        # Create a clean response without internal objects
        result = {
            "status": session_data.get('status'),
            "meet_link": session_data.get('meet_link'),
            "display_name": session_data.get('display_name'),
            "record_path": session_data.get('record_path'),
            "error": session_data.get('error'),
            "start_time": session_data.get('start_time'),
            "end_time": session_data.get('end_time'),
        }
        
        # Add duration if applicable
        if result['start_time']:
            end_time = result['end_time'] or time.time()
            result['duration'] = int(end_time - result['start_time'])
        
        return result
    
    @staticmethod
    def get_all_meetings() -> dict:
        """Get all meeting sessions"""
        from utils.session_store import get_all_sessions
        
        sessions = get_all_sessions()
        results = {}
        
        for session_id, session_data in sessions.items():
            # Filter out internal objects
            clean_data = {
                "status": session_data.get('status'),
                "meet_link": session_data.get('meet_link'),
                "display_name": session_data.get('display_name'),
                "record_path": session_data.get('record_path'),
                "error": session_data.get('error'),
                "start_time": session_data.get('start_time'),
                "end_time": session_data.get('end_time'),
            }
            
            # Add duration if applicable
            if clean_data['start_time']:
                end_time = clean_data['end_time'] or time.time()
                clean_data['duration'] = int(end_time - clean_data['start_time'])
            
            results[session_id] = clean_data
        
        return results

    @staticmethod
    def list_meetings() -> dict:
        """Alias for get_all_meetings"""
        return MeetService.get_all_meetings()
