import os
import time
import logging
import subprocess
import threading
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class DisplayManager:
    """Manages Xvfb display instances for concurrent browser sessions"""
    
    def __init__(self):
        self.displays = {}  # session_id -> (display_num, process)
        self.displays_lock = threading.Lock()
        self.next_display = 100  # Start from display :100
    
    def allocate_display(self, session_id: str, width: int = 1280, height: int = 720, 
                         depth: int = 24) -> Optional[str]:
        """Allocate an Xvfb display for a session"""
        with self.displays_lock:
            # Check if this session already has a display
            if session_id in self.displays:
                display_num, _ = self.displays[session_id]
                return f":{display_num}"
            
            # Find next available display
            display_num = self.next_display
            self.next_display += 1
            
            display_env = f":{display_num}"
            xvfb_cmd = ["Xvfb", display_env, "-screen", "0", 
                        f"{width}x{height}x{depth}", "-ac"]
            
            try:
                logger.info(f"Starting Xvfb on display {display_env} for session {session_id}")
                xvfb_proc = subprocess.Popen(
                    xvfb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                
                # Wait a moment for Xvfb to initialize
                time.sleep(1)
                
                if xvfb_proc.poll() is not None:
                    error_output = xvfb_proc.stderr.read().decode()
                    logger.error(f"Xvfb failed to start: {error_output.strip()}")
                    return None
                
                self.displays[session_id] = (display_num, xvfb_proc)
                return display_env
                
            except Exception as e:
                logger.error(f"Error starting Xvfb: {str(e)}")
                return None
    
    def get_display(self, session_id: str) -> Optional[str]:
        """Get the display number for an existing session"""
        with self.displays_lock:
            if session_id in self.displays:
                display_num, _ = self.displays[session_id]
                return f":{display_num}"
            return None
    
    def release_display(self, session_id: str) -> bool:
        """Release the display for a session"""
        with self.displays_lock:
            if session_id not in self.displays:
                return False
            
            display_num, xvfb_proc = self.displays.pop(session_id)
            try:
                if xvfb_proc and xvfb_proc.poll() is None:
                    xvfb_proc.terminate()
                    xvfb_proc.wait(timeout=5)
                    if xvfb_proc.poll() is None:
                        xvfb_proc.kill()
                logger.info(f"Released display :{display_num} for session {session_id}")
                return True
            except Exception as e:
                logger.error(f"Error releasing display :{display_num}: {str(e)}")
                return False

# Global instance for use throughout the application
display_manager = DisplayManager()
