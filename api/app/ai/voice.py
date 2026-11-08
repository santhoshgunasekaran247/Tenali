import base64
import binascii
import hashlib
import io
import logging
import os
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING

from fastapi import HTTPException
from openai import APIConnectionError, APIStatusError, OpenAI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai.schemas import VoiceInput
from app.services.feature_controls import company_features, lock_policy

logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 12 * 1024 * 1024


def normalize_recording(encoded: str) -> tuple[bytes, Decimal]:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(422, "Invalid voice recording encoding.") from error
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(422, "Voice recordings must be non-empty and no larger than 12 MB.")
    try:
        with wave.open(io.BytesIO(raw), "rb") as recording:
            rate, frames = recording.getframerate(), recording.getnframes()
            if (recording.getnchannels() != 1 or recording.getsampwidth() != 2
                    or recording.getcomptype() != "NONE" or not 8000 <= rate <= 96000):
                raise HTTPException(422, "Use the assistant microphone: mono 16-bit PCM WAV is required.")
            if not rate / 2 <= frames <= rate * 60:
                raise HTTPException(422, "Record between half a second and 60 seconds.")
            samples = recording.readframes(frames + 1)
            if len(samples) != frames * 2:
                raise HTTPException(422, "The voice recording is truncated.")
    except (wave.Error, EOFError) as error:
        raise HTTPException(422, "This voice recording could not be safely decoded.") from error
    output = io.BytesIO()
    with wave.open(output, "wb") as normalized:
        normalized.setnchannels(1)
        normalized.setsampwidth(2)
        normalized.setframerate(rate)
        normalized.writeframes(samples)
    seconds = (Decimal(frames) / Decimal(rate)).quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
    return output.getvalue(), seconds


def audio_cost(seconds: Decimal, rate: Decimal) -> Decimal:
    return (seconds * rate / 60).quantize(Decimal("0.00000001"), rounding=ROUND_CEILING)


@dataclass(frozen=True)
class TranscriptionResult:
    transcript: str | None
    seconds: Decimal | None
    error: str | None = None


class TranscriptionProvider:
    def transcribe(self, audio: bytes, language: str, config: dict) -> TranscriptionResult:
        languages = ["en", "ta"] if language == "auto" else [language]
        try:
            with OpenAI(base_url="https://api.openai.com/v1", timeout=config["timeout_seconds"], max_retries=0) as client:
                response = client.audio.transcriptions.create(
                    model=config["transcription_model"], file=("voice.wav", audio, "audio/wav"),
                    response_format="json", extra_body={"languages": languages})
        except APIConnectionError:
            logger.warning("Voice provider transport outcome unknown")
            return TranscriptionResult(None, None, "provider_unknown")
        except APIStatusError as error:
            logger.warning("Voice provider rejected request: HTTP %s", error.status_code)
            return TranscriptionResult(None, None, "provider_rejected")
        usage = response.usage
        seconds = None
        if usage is not None and usage.type == "duration":
            candidate = Decimal(str(usage.seconds))
            if candidate.is_finite() and 0 < candidate <= 60:
                seconds = candidate
        if seconds is None:
            logger.warning("Voice response has missing or unsupported duration usage")
        transcript = response.text.strip() if isinstance(response.text, str) else ""
        if (not transcript or len(transcript) > 4000
                or any(ord(char) < 32 and char not in "\r\n\t" for char in transcript)):
            logger.warning("Voice response was not a usable bounded transcript")
            return TranscriptionResult(None, seconds, "invalid_transcript")
        return TranscriptionResult(transcript, seconds)


class VoiceService:
    def __init__(self, assistant):
        self.assistant = assistant
        self.db, self.scope = assistant.db, assistant.scope

    def get(self, conversation_id, client_key):
        try:
            return self._get(conversation_id, client_key)
        except DBAPIError:
            self.db.rollback()
            logger.error("Saved voice outcome could not be read")
            raise HTTPException(503, "Saved voice outcome could not be read. Check again with the SAME request reference; do not submit a replacement automatically.") from None

    def _get(self, conversation_id, client_key):
        self.assistant.lock_conversation(conversation_id)
        self.assistant.conversation(conversation_id)
        row = self.db.execute(text("""select id,status,transcript,error_code,deadline,expires_at
            from ai_voice_requests where company_id=:company and user_id=:user
            and conversation_id=:conversation and client_key=:key"""),
            {**self.scope, "conversation": str(conversation_id), "key": str(client_key)}).mappings().first()
        if not row:
            raise HTTPException(404, "Voice request not found. No saved transcription is available.")
        result = dict(row)
        now = datetime.now(timezone.utc)
        if result["expires_at"] <= now:
            self.db.execute(text("""update ai_voice_requests set transcript=null where id=:id
                and company_id=:company and user_id=:user"""), {**self.scope, "id": result["id"]})
            result["transcript"] = None
            result["error_code"] = "transcript_expired"
        if result["status"] == "pending" and result["deadline"] <= now:
            result["status"] = "unknown"
            result["error_code"] = "provider_unknown"
        self.db.commit()
        return {key: result[key] for key in ("id", "status", "transcript", "error_code", "expires_at")}

    def transcribe(self, conversation_id, payload: VoiceInput):
        try:
            return self._transcribe(conversation_id, payload)
        except DBAPIError:
            self.db.rollback()
            logger.error("Voice database outcome unconfirmed; recover the same request reference")
            raise HTTPException(503, "Voice outcome is unconfirmed. Check the saved transcription with the SAME request reference; do not record or submit a replacement automatically.") from None

    def _transcribe(self, conversation_id, payload: VoiceInput):
        audio, seconds = normalize_recording(payload.data_base64)
        audio_hash = hashlib.sha256(audio).hexdigest()
        self.assistant.lock_conversation(conversation_id)
        conversation = self.assistant.conversation(conversation_id)
        existing = self.db.execute(text("""select audio_hash,language from ai_voice_requests
            where company_id=:company and user_id=:user and conversation_id=:conversation and client_key=:key"""),
            {**self.scope, "conversation": str(conversation_id), "key": str(payload.client_key)}).mappings().first()
        if existing:
            if existing["audio_hash"] != audio_hash or existing["language"] != payload.language:
                raise HTTPException(409, "This voice request reference already belongs to a different recording or language.")
            return self.get(conversation_id, payload.client_key)
        lock_policy(self.db)
        config = self.assistant.require_enabled()
        if (conversation["status"] != "active" or not config["voice_inputs_enabled"]
                or config["transcription_model"] != "gpt-transcribe"
                or config["transcription_model"] not in {model.strip() for model in os.getenv("OPENAI_ALLOWED_MODELS", "").split(",")}
                or config["transcription_cost_per_minute"] <= 0):
            raise HTTPException(403, "Voice requires active AI access, an enabled allowlisted transcription model and per-minute pricing.")
        if self.db.execute(text("""select 1 from ai_voice_requests where company_id=:company and user_id=:user
                and conversation_id=:conversation and status='pending' and deadline>now()"""),
                {**self.scope, "conversation": str(conversation_id)}).first():
            raise HTTPException(409, "A voice request is still processing. Check its saved transcription first.")
        if self.db.execute(text("""select 1 from ai_messages where company_id=:company and user_id=:user
                and conversation_id=:conversation and status='pending' and deadline>now()"""),
                {**self.scope, "conversation": str(conversation_id)}).first():
            raise HTTPException(409, "A chat reply is still processing. Wait before transcribing voice.")
        now = datetime.now(timezone.utc)
        voice_id = self.db.execute(text("""insert into ai_voice_requests(company_id,user_id,conversation_id,client_key,
            audio_hash,language,audio_seconds,deadline,expires_at)
            values(:company,:user,:conversation,:key,:hash,:language,:seconds,:deadline,:expires) returning id"""),
            {**self.scope, "conversation": str(conversation_id), "key": str(payload.client_key), "hash": audio_hash,
             "language": payload.language, "seconds": seconds, "deadline": now + timedelta(seconds=config["timeout_seconds"] + 30),
             "expires": min(conversation["expires_at"], now + timedelta(minutes=10))}).scalar_one()
        try:
            reservation = self.db.execute(text("select tenali_ai_reserve_voice(:voice,:model)"),
                {"voice": voice_id, "model": config["transcription_model"]}).scalar_one()
        except DBAPIError as error:
            self.db.rollback()
            if getattr(error.orig, "sqlstate", None) == "P0001":
                raise HTTPException(429, "Tenant AI request/spending limit reached. Voice shares the chat budget.") from error
            if getattr(error.orig, "sqlstate", None) == "42501":
                raise HTTPException(403, "Voice access or configuration changed. Refresh AI settings.") from error
            raise
        self.assistant.audit(conversation_id, "VOICE_RESERVED", payload.client_key)
        self.db.commit()
        current = self.assistant.recheck_before_provider(config)
        result = (TranscriptionProvider().transcribe(audio, payload.language, current)
                  if current is not None else TranscriptionResult(None, Decimal(0), "access_changed"))
        self.finish(conversation_id, voice_id, reservation, payload.client_key, result)
        return self.get(conversation_id, payload.client_key)

    def finish(self, conversation_id, voice_id, reservation_id, client_key, result: TranscriptionResult):
        self.assistant.lock_conversation(conversation_id)
        reservation = self.db.execute(text("""select audio_rate,audio_seconds,reserved_cost from ai_usage_reservations
            where id=:id and company_id=:company and user_id=:user for update"""),
            {**self.scope, "id": reservation_id}).mappings().one()
        known = result.seconds is not None and 0 <= result.seconds <= reservation["audio_seconds"]
        cost = audio_cost(result.seconds, reservation["audio_rate"]) if known and result.seconds is not None else reservation["reserved_cost"]
        if not known:
            logger.warning("Voice duration remains unconfirmed; reservation retained")
        conversation = self.db.execute(text("""select status,expires_at from ai_conversations where id=:id
            and company_id=:company and user_id=:user"""), {**self.scope, "id": str(conversation_id)}).mappings().one()
        permitted = self.db.execute(text("select tenali_ai_member_active()")).scalar_one()
        features = company_features(self.db, self.scope["company"])
        permitted = permitted and features["ai"]["effective_enabled"] and features["voice_inputs_enabled"]
        transcript = result.transcript if permitted and conversation["status"] == "active" and conversation["expires_at"] > datetime.now(timezone.utc) else None
        status = "completed" if transcript else ("failed" if known else "unknown")
        error = result.error or ("access_changed" if result.transcript and not transcript else "usage_unknown" if not known else None)
        self.db.execute(text("""update ai_usage_reservations set status=:status,charged_tokens=0,charged_cost=:cost
            where id=:id and company_id=:company and user_id=:user"""),
            {**self.scope, "id": reservation_id, "status": "settled" if known else "unknown", "cost": cost})
        self.db.execute(text("""insert into ai_usage_logs(company_id,user_id,reservation_id,model,status,estimated_cost,error_code)
            select company_id,user_id,id,model,:status,:cost,:error from ai_usage_reservations
            where id=:id and company_id=:company and user_id=:user"""),
            {**self.scope, "id": reservation_id, "status": status, "cost": cost, "error": error})
        self.db.execute(text("""update ai_voice_requests set status=:status,transcript=case when expires_at>now() then :transcript else null end,
            error_code=:error where id=:id and company_id=:company and user_id=:user"""),
            {**self.scope, "id": voice_id, "status": status, "transcript": transcript, "error": error})
        self.assistant.audit(conversation_id, f"VOICE_{status.upper()}", client_key)
        self.db.commit()
