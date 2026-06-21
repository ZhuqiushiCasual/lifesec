from fastapi import APIRouter, Depends

from app.schemas.voice import VoiceTranscribeRequest, VoiceTranscribeResponse
from app.services.ai.client import get_openai_client
from app.services.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/voice", tags=["Voice"])


@router.post("/transcribe", response_model=VoiceTranscribeResponse)
async def transcribe_voice(
    data: VoiceTranscribeRequest,
    user: User = Depends(get_current_user),
):
    import base64

    client = get_openai_client()
    audio_bytes = base64.b64decode(data.audio_base64)
    transcript = await client.audio.transcriptions.create(
        model="whisper-1",
        file=("audio." + data.format, audio_bytes),
    )
    text = transcript.text

    intent_resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": "判断这段文字是生活记录还是财务记录。只返回 JSON: {\"intent\": \"life\" | \"finance\"}",
            },
            {"role": "user", "content": text},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    import json

    intent = json.loads(intent_resp.choices[0].message.content).get("intent", "life")

    return VoiceTranscribeResponse(text=text, intent=intent)
