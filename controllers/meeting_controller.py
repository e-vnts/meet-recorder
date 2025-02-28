# controllers/meeting_controller.py
# Defines REST endpoints for joining a meeting, checking status, and leaving a meeting.
import logging
import os
import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Path
from typing import Dict, List, Optional
from pydantic import BaseModel

from utils import session_store
from services import google_meet_bot, zoom_bot
from models.meeting import MeetingRequest, MeetingResponse, MeetingStatusResponse, MeetingListResponse, MeetingStatus
from services.meet_service import MeetService

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
logger = logging.getLogger(__name__)

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

@router.post("/", response_model=MeetingResponse)
async def start_meeting(request: MeetingRequest):
    """Start a new meeting recording session"""
    try:
        # Ensure the recording directory exists
        os.makedirs(os.path.dirname(request.record_path), exist_ok=True)
        
        # Start the meeting
        session_id = MeetService.start_meeting(
            meet_link=str(request.meet_link),
            display_name=request.display_name,
            record_path=request.record_path,
            screen_resolution=request.screen_resolution,
            show_browser=request.show_browser,
            **(request.additional_options or {})
        )
        
        return MeetingResponse(
            session_id=session_id,
            status=MeetingStatus.PENDING,
            message="Meeting session started successfully"
        )
    
    except Exception as e:
        logger.exception(f"Error starting meeting: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start meeting: {str(e)}")

@router.get("/{session_id}", response_model=MeetingStatusResponse)
async def get_meeting_status(session_id: str = Path(..., description="Meeting session ID")):
    """Get the current status of a meeting session"""
    try:
        status = MeetService.get_meeting_status(session_id)
        
        if status.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=f"Meeting session {session_id} not found")
        
        return MeetingStatusResponse(
            session_id=session_id,
            status=status.get("status"),
            recording_path=status.get("record_path"),
            duration=status.get("duration"),
            error=status.get("error")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting meeting status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get meeting status: {str(e)}")

@router.post("/{session_id}/stop", response_model=MeetingStatusResponse)
async def stop_meeting(session_id: str = Path(..., description="Meeting session ID")):
    """Stop a meeting recording session"""
    try:
        success = MeetService.stop_meeting(session_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Meeting session {session_id} not found or already stopped")
        
        # Get updated status
        status = MeetService.get_meeting_status(session_id)
        
        return MeetingStatusResponse(
            session_id=session_id,
            status=status.get("status"),
            recording_path=status.get("record_path"),
            duration=status.get("duration"),
            error=status.get("error")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error stopping meeting: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to stop meeting: {str(e)}")

@router.get("/", response_model=MeetingListResponse)
async def list_meetings():
    """List all active meeting sessions"""
    try:
        meetings = MeetService.get_all_meetings()
        
        # Convert to required format
        result = {}
        for session_id, meeting_data in meetings.items():
            result[session_id] = MeetingStatusResponse(
                session_id=session_id,
                status=meeting_data.get("status"),
                recording_path=meeting_data.get("record_path"),
                duration=meeting_data.get("duration"),
                error=meeting_data.get("error")
            )
            
        return MeetingListResponse(sessions=result)
    
    except Exception as e:
        logger.exception(f"Error listing meetings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list meetings: {str(e)}")
