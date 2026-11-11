from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.ai.schemas import ConversationCreate, ConversationOut, ConversationUpdate, MessageCreate, PreferenceUpdate, AIUpload, VoiceInput
from app.ai.voice import VoiceService
from app.ai.media import MediaService
from app.ai.service import AssistantService
from app.ai.capabilities import available_capabilities, current_identity
from app.dependencies import get_db
from app.ai.actions import DraftCreate, DraftEdit, DraftApproval, ExecutionApproval
from app.ai.drafts import DraftService, available_actions
from app.ai.execution import ExecutionService

router = APIRouter()


def assistant(request: Request, db=Depends(get_db)):
    return AssistantService(db, request.state.tenant)


@router.get("/executions/{execution_id}/report")
def private_report(execution_id: UUID, service=Depends(assistant)):
    from app.ai.reports import download
    return download(service, execution_id)


@router.post("/conversations/{conversation_id}/voice")
def transcribe_voice(conversation_id: UUID, payload: VoiceInput, service=Depends(assistant)):
    return VoiceService(service).transcribe(conversation_id, payload)


@router.get("/conversations/{conversation_id}/voice/{client_key}")
def voice_outcome(conversation_id: UUID, client_key: UUID, service=Depends(assistant)):
    return VoiceService(service).get(conversation_id, client_key)


@router.post("/conversations/{conversation_id}/attachments", status_code=201)
def upload_attachment(conversation_id: UUID, payload: AIUpload, service=Depends(assistant)):
    return MediaService(service).upload(conversation_id, payload)


@router.delete("/attachments/{attachment_id}")
def remove_attachment(attachment_id: UUID, service=Depends(assistant)):
    return MediaService(service).remove(attachment_id)


@router.get("/actions")
def actions(service=Depends(assistant)):
    service.require_enabled()
    identity = current_identity(service.db, service.identity)
    return {"items": available_actions(service.db, identity)}


@router.get("/conversations/{conversation_id}/drafts")
def drafts(conversation_id: UUID, offset: int = Query(0, ge=0), service=Depends(assistant)):
    return DraftService(service).list(conversation_id, offset)


@router.get("/drafts/{draft_id}")
def draft(draft_id: UUID, service=Depends(assistant)):
    return DraftService(service).get(draft_id)


@router.post("/conversations/{conversation_id}/drafts", status_code=201)
def create_draft(conversation_id: UUID, payload: DraftCreate, service=Depends(assistant)):
    return DraftService(service).create(conversation_id, payload)


@router.patch("/drafts/{draft_id}")
def edit_draft(draft_id: UUID, payload: DraftEdit, service=Depends(assistant)):
    return DraftService(service).edit(draft_id, payload)


@router.post("/drafts/{draft_id}/validate")
def validate_draft(draft_id: UUID, expected_version: int = Query(ge=1), service=Depends(assistant)):
    return DraftService(service).validate(draft_id, expected_version)


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: UUID, payload: DraftApproval, service=Depends(assistant)):
    return DraftService(service).approve(draft_id, payload)


@router.post("/drafts/{draft_id}/execute")
def execute_draft(draft_id: UUID, payload: ExecutionApproval, service=Depends(assistant)):
    return ExecutionService(service).execute(draft_id, payload)


@router.get("/drafts/{draft_id}/execution")
def draft_execution(draft_id: UUID, expected_version: int = Query(ge=1), service=Depends(assistant)):
    return {"execution": ExecutionService(service).for_draft(draft_id, expected_version)}


@router.get("/executions/{execution_id}")
def execution(execution_id: UUID, service=Depends(assistant)):
    return ExecutionService(service).get(execution_id)


@router.delete("/drafts/{draft_id}")
def discard_draft(draft_id: UUID, expected_version: int = Query(ge=1), service=Depends(assistant)):
    return DraftService(service).discard(draft_id, expected_version)


@router.get("/capabilities")
def capabilities(service=Depends(assistant)):
    service.require_enabled()
    identity = current_identity(service.db, service.identity)
    return {"items": available_capabilities(service.db, identity)}


@router.get("/conversations")
def conversations(search: str = Query("", max_length=120), archived: bool = False, offset: int = Query(0, ge=0),
                  service=Depends(assistant)):
    return service.list_conversations(search, archived, offset)


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create(payload: ConversationCreate, service=Depends(assistant)):
    return service.create(payload)


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def conversation(conversation_id: UUID, service=Depends(assistant)):
    return service.conversation(conversation_id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def update(conversation_id: UUID, payload: ConversationUpdate, service=Depends(assistant)):
    return service.update(conversation_id, payload)


@router.delete("/conversations/{conversation_id}")
def delete(conversation_id: UUID, expected_version: int = Query(ge=1), service=Depends(assistant)):
    return service.delete(conversation_id, expected_version)


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: UUID, offset: int = Query(0, ge=0), client_key: UUID | None = None, service=Depends(assistant)):
    return service.messages(conversation_id, offset, client_key)


@router.post("/conversations/{conversation_id}/messages")
def send(conversation_id: UUID, payload: MessageCreate, service=Depends(assistant)):
    return service.send(conversation_id, payload)


@router.get("/context")
def context(service=Depends(assistant)):
    return service.preferences()


@router.put("/context/preferences/{preference}")
def preference(preference: Literal["language", "instructions"], payload: PreferenceUpdate, service=Depends(assistant)):
    return service.save_preference(preference, payload.value)


@router.delete("/context/preferences/{preference}")
def delete_preference(preference: Literal["language", "instructions"], service=Depends(assistant)):
    return service.delete_preference(preference)


@router.get("/usage")
def usage(service=Depends(assistant)):
    return service.usage()
