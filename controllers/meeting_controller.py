# controllers/meeting_controller.py
# Defines REST endpoints for joining a meeting, checking status, and leaving a meeting.
import logging
import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from utils import session_store
from services import google_meet_bot, zoom_bot

logger = logging.getLogger(__name__)
router = APIRouter()

# Pydantic models for request validation.
class JoinRequest(BaseModel):
    meetingUrl: str
    platform: str  # "google" for Google Meet or "zoom" for Zoom

class LeaveRequest(BaseModel):
    sessionId: str

@router.post("/join")
async def join_meeting(join_request: JoinRequest, background_tasks: BackgroundTasks):
    """
    API endpoint to join a meeting.
    Generates a unique sessionId and spawns a background task to start the Selenium session.
    """
    session_id = str(uuid.uuid4())
    logger.info(f"Received join request for {join_request.platform} meeting: {join_request.meetingUrl}, session_id: {session_id}")

    # Add session with initial "joining" status.
    session_store.add_session(session_id, {"status": "joining", "driver": None, "platform": join_request.platform})
    
    try:
        if join_request.platform.lower() == "google":
            background_tasks.add_task(google_meet_bot.join_meeting, join_request.meetingUrl, session_id)
        elif join_request.platform.lower() == "zoom":
            background_tasks.add_task(zoom_bot.join_meeting, join_request.meetingUrl, session_id)
        else:
            session_store.remove_session(session_id)
            logger.error(f"Unsupported platform requested: {join_request.platform}")
            raise HTTPException(status_code=400, detail="Unsupported platform. Use 'google' or 'zoom'.")
    except Exception as e:
        logger.exception(f"Error processing join request: {str(e)}")
        session_store.remove_session(session_id)
        raise HTTPException(status_code=500, detail="Failed to process join request.")

    return {"sessionId": session_id, "status": "joining"}

@router.get("/status/{session_id}")
async def get_status(session_id: str):
    """
    API endpoint to get the current status of a session.
    Returns whether the meeting session is joining, joined, or in an error state.
    """
    session = session_store.get_session(session_id)
    if not session:
        logger.error(f"Status request for non-existent session: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")
    
    logger.info(f"Status for session {session_id}: {session.get('status', 'unknown')}")
    return {"sessionId": session_id, "status": session.get("status", "unknown")}

@router.post("/leave")
async def leave_meeting(leave_request: LeaveRequest):
    """
    API endpoint to leave a meeting.
    Closes the Selenium session associated with the given sessionId.
    """
    session = session_store.get_session(leave_request.sessionId)
    if not session:
        logger.error(f"Leave request for non-existent session: {leave_request.sessionId}")
        raise HTTPException(status_code=404, detail="Session not found")
    
    platform = session.get("platform")
    try:
        if platform.lower() == "google":
            google_meet_bot.leave_meeting(leave_request.sessionId)
        elif platform.lower() == "zoom":
            zoom_bot.leave_meeting(leave_request.sessionId)
        else:
            logger.error(f"Unsupported platform in session {leave_request.sessionId}: {platform}")
            raise HTTPException(status_code=400, detail="Unsupported platform")
    except Exception as e:
        logger.exception(f"Error leaving meeting for session {leave_request.sessionId}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error leaving meeting")
    
    session_store.remove_session(leave_request.sessionId)
    logger.info(f"Session {leave_request.sessionId} has been closed and removed.")
    return {"sessionId": leave_request.sessionId, "status": "left"}
