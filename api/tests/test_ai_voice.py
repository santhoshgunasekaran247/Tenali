import base64
import io
import json
import os
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.ai.schemas import ConversationCreate, VoiceInput
from app.ai.voice import normalize_recording, audio_cost, TranscriptionProvider, TranscriptionResult, VoiceService
from app.services.feature_controls import AIConfig
from test_ai_execution import AIDatabaseFixture


def recording(seconds=1, rate=16000, channels=1, width=2):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(b"\x01" * int(rate * seconds) * channels * width)
    return base64.b64encode(output.getvalue()).decode()


class VoiceUnitTests(unittest.TestCase):
    def test_verified_duration_and_bounds(self):
        raw, seconds = normalize_recording(recording(1.125))
        self.assertEqual(seconds, Decimal("1.125000"))
        with wave.open(io.BytesIO(raw)) as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 16000))
        for data in ("invalid", base64.b64encode(b"not audio").decode(), recording(0.49), recording(60.01),
                     recording(channels=2), recording(width=1), recording(rate=4000),
                     base64.b64encode(base64.b64decode(recording())[:-2]).decode()):
            with self.subTest(data=data[:16]), self.assertRaises(HTTPException):
                normalize_recording(data)
        self.assertEqual(normalize_recording(recording(60))[1], Decimal(60))
        self.assertEqual(audio_cost(Decimal(1), Decimal("0.0045")), Decimal("0.00007500"))

    def test_voice_config_is_separate_default_off_and_duration_only(self):
        self.assertFalse(AIConfig().voice_inputs_enabled)
        for values in ({"voice_inputs_enabled": True}, {"voice_inputs_enabled": True,
                       "transcription_model": "gpt-4o-mini-transcribe", "transcription_cost_per_minute": "0.003"}):
            with self.assertRaises(ValueError):
                AIConfig(**values)
        self.assertTrue(AIConfig(voice_inputs_enabled=True, transcription_model="gpt-transcribe",
                                 transcription_cost_per_minute="0.0045").voice_inputs_enabled)

    def test_provider_language_hints_and_duration_usage_without_chat_context(self):
        from openai.types.audio import Transcription
        response = Transcription(text="English and Tamil transcript", usage={"type": "duration", "seconds": 1})
        config = {"transcription_model": "gpt-transcribe", "timeout_seconds": 30}
        for language, hints in (("auto", ["en", "ta"]), ("en", ["en"]), ("ta", ["ta"])):
            with patch("app.ai.voice.OpenAI") as provider:
                provider.return_value.__enter__.return_value.audio.transcriptions.create.return_value = response
                result = TranscriptionProvider().transcribe(b"normalized PCM", language, config)
                request = provider.return_value.__enter__.return_value.audio.transcriptions.create.call_args.kwargs
                self.assertEqual(request["extra_body"], {"languages": hints})
                self.assertEqual(request["file"], ("voice.wav", b"normalized PCM", "audio/wav"))
                self.assertNotIn("prompt", request)
                self.assertEqual(result.seconds, Decimal(1))
                self.assertEqual(provider.call_args.kwargs["max_retries"], 0)
        with patch("app.ai.voice.OpenAI") as provider:
            provider.return_value.__enter__.return_value.audio.transcriptions.create.return_value = Transcription(text="text")
            self.assertIsNone(TranscriptionProvider().transcribe(b"PCM", "auto", config).seconds)
        with patch("app.ai.voice.OpenAI") as provider:
            provider.return_value.__enter__.return_value.audio.transcriptions.create.return_value = Transcription(text=" ")
            self.assertEqual(TranscriptionProvider().transcribe(b"PCM", "auto", config).error, "invalid_transcript")


@unittest.skipUnless(os.getenv("TENALI_TEST_DB") == "1", "Authorised isolated database required")
class VoiceDatabaseTests(AIDatabaseFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.factory() as db:
            config = db.execute(text("select config from ai_platform_settings where id=true")).scalar_one()
            config.update(voice_inputs_enabled=True, transcription_model="gpt-transcribe", transcription_cost_per_minute="0.0045")
            db.execute(text("update ai_platform_settings set config=cast(:config as jsonb),version=version+1"),
                       {"config": json.dumps(config)})
            db.commit()

    def request(self, db):
        assistant = self.service(db)
        conversation = assistant.create(ConversationCreate())
        return assistant, conversation, VoiceInput(client_key=uuid4(), data_base64=recording())

    def test_private_replay_metering_and_transcript_scrubbing(self):
        with self.factory() as db:
            assistant, conversation, request = self.request(db)
            with patch("app.ai.voice.TranscriptionProvider.transcribe",
                       return_value=TranscriptionResult("Synthetic voice text", Decimal(1))) as provider:
                outcome = VoiceService(assistant).transcribe(conversation["id"], request)
                replay = VoiceService(assistant).transcribe(conversation["id"], request)
                self.assertEqual(provider.call_count, 1)
                self.assertEqual(outcome["id"], replay["id"])
                self.assertEqual(outcome["transcript"], "Synthetic voice text")
            reservation = db.execute(text("select * from ai_usage_reservations where voice_id=:id"),
                                     {"id": outcome["id"]}).mappings().one()
            self.assertEqual((reservation["charged_tokens"], reservation["charged_cost"], reservation["status"]),
                             (0, Decimal("0.00007500"), "settled"))
            self.assertIsNone(reservation["message_id"])
            self.assertEqual(db.execute(text("select count(*) from ai_messages where conversation_id=:id"),
                                        {"id": conversation["id"]}).scalar_one(), 0)
            with self.assertRaises(HTTPException) as changed:
                VoiceService(assistant).transcribe(conversation["id"], request.model_copy(update={"language": "ta"}))
            self.assertEqual(changed.exception.status_code, 409)
            latest = assistant.conversation(conversation["id"])
            assistant.delete(conversation["id"], latest["version"])
            self.assertIsNone(db.execute(text("select transcript from ai_voice_requests where id=:id"),
                                        {"id": outcome["id"]}).scalar_one())

    def test_unknown_usage_is_reserved_and_never_resent(self):
        with self.factory() as db:
            assistant, conversation, request = self.request(db)
            with patch("app.ai.voice.TranscriptionProvider.transcribe",
                       return_value=TranscriptionResult(None, None, "provider_unknown")) as provider:
                outcome = VoiceService(assistant).transcribe(conversation["id"], request)
                VoiceService(assistant).transcribe(conversation["id"], request)
                self.assertEqual(provider.call_count, 1)
            self.assertEqual(outcome["status"], "unknown")
            reservation = db.execute(text("select status,charged_cost,reserved_cost from ai_usage_reservations where voice_id=:id"),
                                     {"id": outcome["id"]}).mappings().one()
            self.assertEqual(reservation["status"], "unknown")
            self.assertEqual(reservation["charged_cost"], reservation["reserved_cost"])

    def test_lost_commit_acknowledgement_does_not_duplicate_provider_request(self):
        with self.factory() as db:
            assistant, conversation, request = self.request(db)
            commit = db.commit
            def ambiguous():
                commit()
                raise OperationalError("Synthetic lost acknowledgement", {}, Exception("synthetic"))
            with patch.object(db, "commit", side_effect=ambiguous), patch("app.ai.voice.TranscriptionProvider.transcribe") as provider:
                with self.assertRaises(HTTPException) as caught:
                    VoiceService(assistant).transcribe(conversation["id"], request)
                self.assertEqual(caught.exception.status_code, 503)
                provider.assert_not_called()
        with self.factory() as db:
            with patch("app.ai.voice.TranscriptionProvider.transcribe") as provider:
                outcome = VoiceService(self.service(db)).transcribe(conversation["id"], request)
                self.assertEqual(outcome["status"], "pending")
                provider.assert_not_called()

    def test_quota_combines_chat_and_voice_and_owner_isolation(self):
        from app.ai.schemas import AssistantOutput, MessageCreate
        from app.ai.provider import ProviderResult
        with self.factory() as db:
            assistant, conversation, request = self.request(db)
            with patch("app.ai.service.OpenAIProvider.respond",
                       return_value=ProviderResult(AssistantOutput(reply="Synthetic chat", clarification=None), 50, 0, 10, "mock")):
                assistant.send(conversation["id"], MessageCreate(content="Synthetic quota chat", client_key=uuid4()))
        with self.factory() as admin:
            admin.execute(text("""insert into ai_tenant_limits(company_id,config) values(:company,cast(:config as jsonb))
                on conflict(company_id) do update set config=excluded.config"""),
                {"company": self.identity["company_id"], "config": json.dumps({"daily_request_limit": 1})})
            admin.commit()
        try:
            with self.factory() as db:
                with patch("app.ai.voice.TranscriptionProvider.transcribe") as provider:
                    with self.assertRaises(HTTPException) as caught:
                        VoiceService(self.service(db)).transcribe(conversation["id"], request)
                    self.assertEqual(caught.exception.status_code, 429)
                    provider.assert_not_called()
            other = {**self.identity, "user_id": str(uuid4())}
            with self.factory() as db:
                db.info["tenant_context"] = other
                from app.ai.service import AssistantService
                self.assertEqual(db.execute(text("select count(*) from ai_voice_requests")).scalar_one(), 0)
                with self.assertRaises(HTTPException):
                    VoiceService(AssistantService(db, other)).get(conversation["id"], request.client_key)
        finally:
            with self.factory() as db:
                db.execute(text("delete from ai_tenant_limits where company_id=:company"), {"company": self.identity["company_id"]})
                db.commit()

    def test_expiry_and_concurrent_submission(self):
        with self.factory() as db:
            _, conversation, request = self.request(db)
        def submit():
            with self.factory() as db:
                return VoiceService(self.service(db)).transcribe(conversation["id"], request)
        with patch("app.ai.voice.TranscriptionProvider.transcribe",
                   return_value=TranscriptionResult("Synthetic concurrent text", Decimal(1))) as provider:
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: submit(), range(2)))
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(outcomes[0]["id"], outcomes[1]["id"])
        with self.factory() as admin:
            admin.execute(text("update ai_voice_requests set expires_at=now()-interval '1 second' where id=:id"),
                          {"id": outcomes[0]["id"]})
            admin.commit()
        with self.factory() as db:
            result = VoiceService(self.service(db)).get(conversation["id"], request.client_key)
            self.assertIsNone(result["transcript"])
            self.assertEqual(result["error_code"], "transcript_expired")

    def test_revoked_voice_and_viewer_cannot_call_provider(self):
        with self.factory() as db:
            _, conversation, request = self.request(db)
        with self.factory() as admin:
            original = admin.execute(text("select config from ai_platform_settings where id=true")).scalar_one()
            changed = {**original, "voice_inputs_enabled": False}
            admin.execute(text("update ai_platform_settings set config=cast(:config as jsonb),version=version+1"),
                          {"config": json.dumps(changed)})
            admin.commit()
        try:
            with self.factory() as db, patch("app.ai.voice.TranscriptionProvider.transcribe") as provider:
                with self.assertRaises(HTTPException) as caught:
                    VoiceService(self.service(db)).transcribe(conversation["id"], request)
                self.assertEqual(caught.exception.status_code, 403)
                provider.assert_not_called()
        finally:
            with self.factory() as admin:
                admin.execute(text("update ai_platform_settings set config=cast(:config as jsonb),version=version+1"),
                              {"config": json.dumps(original)})
                admin.execute(text("update tenant_memberships set role='viewer' where company_id=:company and user_id=:user"),
                              {"company": self.identity["company_id"], "user": self.identity["user_id"]})
                admin.commit()
        try:
            with self.factory() as db, patch("app.ai.voice.TranscriptionProvider.transcribe") as provider:
                with self.assertRaises(HTTPException) as caught:
                    VoiceService(self.service(db)).transcribe(conversation["id"], request)
                self.assertEqual(caught.exception.status_code, 403)
                provider.assert_not_called()
        finally:
            with self.factory() as admin:
                admin.execute(text("update tenant_memberships set role='owner' where company_id=:company and user_id=:user"),
                              {"company": self.identity["company_id"], "user": self.identity["user_id"]})
                admin.commit()

    def test_voice_spend_blocks_chat_and_postcommit_recovery_does_not_resend(self):
        from app.ai.schemas import MessageCreate
        with self.factory() as db:
            assistant, conversation, request = self.request(db)
            with patch("app.ai.voice.TranscriptionProvider.transcribe",
                       return_value=TranscriptionResult("Synthetic recovery transcript", Decimal(1))) as provider:
                gateway = VoiceService(assistant)
                with patch.object(gateway, "get", side_effect=OperationalError(
                        "Synthetic postcommit read failure", {}, Exception("synthetic"))):
                    with self.assertRaises(HTTPException) as caught:
                        gateway.transcribe(conversation["id"], request)
                    self.assertEqual(caught.exception.status_code, 503)
                outcome = VoiceService(assistant).transcribe(conversation["id"], request)
                self.assertEqual(outcome["transcript"], "Synthetic recovery transcript")
                self.assertEqual(provider.call_count, 1)
        with self.factory() as admin:
            admin.execute(text("""insert into ai_tenant_limits(company_id,config) values(:company,cast(:config as jsonb))
                on conflict(company_id) do update set config=excluded.config"""),
                {"company": self.identity["company_id"], "config": json.dumps({"daily_request_limit": 1})})
            admin.commit()
        try:
            with self.factory() as db, patch("app.ai.service.OpenAIProvider.respond") as provider:
                with self.assertRaises(HTTPException) as caught:
                    self.service(db).send(conversation["id"], MessageCreate(content="Synthetic quota chat", client_key=uuid4()))
                self.assertEqual(caught.exception.status_code, 429)
                provider.assert_not_called()
        finally:
            with self.factory() as admin:
                admin.execute(text("delete from ai_tenant_limits where company_id=:company"), {"company": self.identity["company_id"]})
                admin.commit()

    def test_monthly_spending_reservation_blocks_before_provider(self):
        with self.factory() as db:
            _, conversation, request = self.request(db)
            request = request.model_copy(update={"data_base64": recording(60)})
        with self.factory() as admin:
            original = admin.execute(text("select config from ai_platform_settings where id=true")).scalar_one()
            changed = {**original, "transcription_cost_per_minute": "10"}
            admin.execute(text("update ai_platform_settings set config=cast(:config as jsonb),version=version+1"),
                          {"config": json.dumps(changed)})
            admin.execute(text("""insert into ai_tenant_limits(company_id,config) values(:company,cast(:config as jsonb))
                on conflict(company_id) do update set config=excluded.config"""),
                {"company": self.identity["company_id"], "config": json.dumps({"monthly_cost_limit": 1})})
            admin.commit()
        try:
            with self.factory() as db, patch("app.ai.voice.TranscriptionProvider.transcribe") as provider:
                with self.assertRaises(HTTPException) as caught:
                    VoiceService(self.service(db)).transcribe(conversation["id"], request)
                self.assertEqual(caught.exception.status_code, 429)
                provider.assert_not_called()
                self.assertEqual(db.execute(text("select count(*) from ai_voice_requests where client_key=:key"),
                                            {"key": request.client_key}).scalar_one(), 0)
        finally:
            with self.factory() as admin:
                admin.execute(text("update ai_platform_settings set config=cast(:config as jsonb),version=version+1"),
                              {"config": json.dumps(original)})
                admin.execute(text("delete from ai_tenant_limits where company_id=:company"), {"company": self.identity["company_id"]})
                admin.commit()
