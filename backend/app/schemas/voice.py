from pydantic import BaseModel
from typing import Optional


class VoiceTranscribeRequest(BaseModel):
    audio_base64: str
    format: str = "wav"


class VoiceTranscribeResponse(BaseModel):
    text: str
    intent: Optional[str]
