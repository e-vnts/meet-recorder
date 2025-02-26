# utils/session_store.py
# Provides a thread-safe in-memory store for tracking Selenium sessions.
import threading
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)
sessions = {}
sessions_lock = threading.Lock()

def add_session(session_id: str, session_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """Adds a new session to the store."""
    if session_data is None:
        session_data = {}
    
    with sessions_lock:
        sessions[session_id] = session_data
        logger.info(f"Added session: {session_id}")
    return session_data

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves the session data for a given sessionId."""
    with sessions_lock:
        session = sessions.get(session_id)
        if session is None:
            logger.debug(f"Session {session_id} not found.")
        return session

def update_session(session_id: str, session_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing session with new data. Creates the session if it doesn't exist."""
    with sessions_lock:
        sessions[session_id] = session_data
        logger.debug(f"Updated session: {session_id}")
    return session_data

def remove_session(session_id: str) -> bool:
    """Removes the session from the store."""
    with sessions_lock:
        removed = sessions.pop(session_id, None)
        if removed:
            logger.info(f"Removed session: {session_id}")
            return True
        else:
            logger.debug(f"Attempted to remove non-existent session: {session_id}")
            return False

def get_all_sessions() -> Dict[str, Dict[str, Any]]:
    """Return a copy of all sessions."""
    with sessions_lock:
        return sessions.copy()
