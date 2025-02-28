import asyncio
import logging
import threading
import uuid
import time
from typing import Dict, Any, Callable, Coroutine, Optional, Union

logger = logging.getLogger(__name__)

class BackgroundTaskManager:
    """Manages concurrent background tasks for meeting sessions"""
    
    def __init__(self):
        self.tasks = {}  # session_id -> task info
        self.tasks_lock = threading.Lock()
    
    def start_task(self, session_id: str, task_func: Callable, *args, **kwargs) -> bool:
        """Start a background task for a session"""
        with self.tasks_lock:
            if session_id in self.tasks:
                logger.warning(f"Task for session {session_id} already exists")
                return False
            
            def wrapped_task():
                try:
                    self.tasks[session_id]['status'] = 'running'
                    self.tasks[session_id]['start_time'] = time.time()
                    result = task_func(*args, **kwargs)
                    self.tasks[session_id]['result'] = result
                    self.tasks[session_id]['status'] = 'completed'
                except Exception as e:
                    logger.exception(f"Error in background task for session {session_id}: {str(e)}")
                    self.tasks[session_id]['error'] = str(e)
                    self.tasks[session_id]['status'] = 'error'
                finally:
                    self.tasks[session_id]['end_time'] = time.time()
            
            thread = threading.Thread(target=wrapped_task)
            thread.daemon = True
            
            self.tasks[session_id] = {
                'thread': thread,
                'status': 'starting',
                'start_time': None,
                'end_time': None,
                'result': None,
                'error': None
            }
            
            thread.start()
            logger.info(f"Started background task for session {session_id}")
            return True
    
    def get_task_status(self, session_id: str) -> Dict[str, Any]:
        """Get status of a running task"""
        with self.tasks_lock:
            if session_id not in self.tasks:
                return {'status': 'not_found'}
            
            task_info = self.tasks[session_id].copy()
            # Remove thread from the info as it's not serializable
            if 'thread' in task_info:
                task_info.pop('thread')
                
            # Calculate duration if possible
            if task_info['start_time'] is not None:
                end_time = task_info['end_time'] or time.time()
                task_info['duration'] = int(end_time - task_info['start_time'])
                
            return task_info
    
    def stop_task(self, session_id: str) -> bool:
        """Signal a task to stop (task must handle termination)"""
        with self.tasks_lock:
            if session_id not in self.tasks:
                return False
            
            self.tasks[session_id]['status'] = 'stopping'
            return True
    
    def cleanup_task(self, session_id: str) -> bool:
        """Remove a completed task from the manager"""
        with self.tasks_lock:
            if session_id not in self.tasks:
                return False
            
            # Only remove if task is completed or errored
            status = self.tasks[session_id]['status']
            if status in ['completed', 'error']:
                del self.tasks[session_id]
                logger.info(f"Cleaned up task for session {session_id}")
                return True
            
            return False
    
    def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        """Get all tasks and their statuses"""
        with self.tasks_lock:
            result = {}
            for session_id, task_info in self.tasks.items():
                info_copy = task_info.copy()
                if 'thread' in info_copy:
                    info_copy.pop('thread')
                
                # Calculate duration if possible
                if info_copy['start_time'] is not None:
                    end_time = info_copy['end_time'] or time.time()
                    info_copy['duration'] = int(end_time - info_copy['start_time'])
                
                result[session_id] = info_copy
            
            return result

# Global instance
task_manager = BackgroundTaskManager()
