# utils/session_store.py
# Provides a thread-safe in-memory store for tracking Selenium sessions.
import threading
import logging

logger = logging.getLogger(__name__)
sessions = {}
sessions_lock = threading.Lock()

def add_session(session_id: str, session_data: dict):
    """Adds a new session to the store."""
    with sessions_lock:
        sessions[session_id] = session_data
        logger.info(f"Added session: {session_id}")

def get_session(session_id: str):
    """Retrieves the session data for a given sessionId."""
    with sessions_lock:
        session = sessions.get(session_id)
        if session is None:
            logger.debug(f"Session {session_id} not found.")
        return session

def remove_session(session_id: str):
    """Removes the session from the store."""
    with sessions_lock:
        removed = sessions.pop(session_id, None)
        if removed:
            logger.info(f"Removed session: {session_id}")
        else:
            logger.debug(f"Attempted to remove non-existent session: {session_id}")
        return removed
