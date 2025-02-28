from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any
from enum import Enum


class MeetingStatus(str, Enum):
    PENDING = "pending"
    JOINING = "joining"
    RECORDING = "recording"
    STOPPED = "stopped"
    ERROR = "error"


class MeetingRequest(BaseModel):
    meet_link: HttpUrl
    display_name: str = Field(default="Oracia")
    record_path: Optional[str] = Field(default="recordings/output.mp4")
    screen_resolution: str = Field(default="1280x720")
    show_browser: bool = Field(default=False)
    additional_options: Optional[Dict[str, Any]] = None


class MeetingResponse(BaseModel):
    session_id: str
    status: MeetingStatus
    message: Optional[str] = None


class MeetingStatusResponse(BaseModel):
    session_id: str
    status: MeetingStatus
    recording_path: Optional[str] = None
    duration: Optional[int] = None
    error: Optional[str] = None


class MeetingListResponse(BaseModel):
    sessions: Dict[str, MeetingStatusResponse]
