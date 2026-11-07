from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.ai.schemas import ConversationCreate, ConversationOut, ConversationUpdate, MessageCreate, PreferenceUpdate
from app.ai.service import AssistantService
from app.ai.capabilities import available_capabilities, current_identity
from app.dependencies import get_db

router = APIRouter()


def assistant(request: Request, db=Depends(get_db)):
    return AssistantService(db, request.state.tenant)


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
