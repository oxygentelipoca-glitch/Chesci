from __future__ import annotations

import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.auth import get_current_user, resolve_current_user_id
from app.core.response import api_success
from app.database import engine
from app.models import Conversation, Message
from app.services.rag_service import ask_question

router = APIRouter(tags=["Chat"])


class ChatRequest(BaseModel):
    question: str
    conversation_id: int | None = None
    file_ids: list[int] | None = None
    dense_weight: float = Field(default=1.0, ge=0.0, le=3.0)
    bm25_weight: float = Field(default=1.0, ge=0.0, le=3.0)
    adaptive_retrieval: bool = True
    include_retrieval_debug: bool = False


def _truncate_title(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= 20:
        return cleaned
    return cleaned[:20] + "..."


def _decode_sources(raw: str | None) -> tuple[list, list, dict, dict | None]:
    """Support historical filename lists and new citation-rich source records."""
    if not raw:
        return [], [], {}, None
    value = json.loads(raw)
    if isinstance(value, list):
        return value, [], {}, None
    return (
        value.get("files", []),
        value.get("citations", []),
        value.get("retrieval", {}),
        value.get("debug"),
    )


def _serialize_message(message: Message) -> dict:
    sources, citations, retrieval, debug = _decode_sources(message.sources)
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": sources,
        "citations": citations,
        "retrieval": retrieval,
        "debug": debug,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _load_history(conversation_id: int, user_id: int) -> list[dict[str, str]]:
    """Load recent messages from a conversation for multi-turn context."""
    with Session(engine) as session:
        messages = session.exec(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.user_id == user_id,
            )
            .order_by(Message.created_at.asc())
        ).all()
        return [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]


def _resolve_stored_filenames(
    file_ids: list[int] | None,
    user_id: int,
) -> list[str] | None:
    """Turn file_ids into ``stored_filename`` values for Chroma filtering.

    Returns None when no filter is requested, keeping full-scope search.
    """
    if not file_ids:
        return None

    from app.models import File as FileModel
    with Session(engine) as session:
        files = session.exec(
            select(FileModel).where(
                FileModel.id.in_(file_ids),
                FileModel.user_id == user_id,
            )
        ).all()
        return [os.path.basename(f.filepath) for f in files]


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------

@router.post("/chat")
def chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    with Session(engine) as session:
        user_id = resolve_current_user_id(current_user, session)

        conversation = None
        if request.conversation_id is not None:
            conversation = session.get(Conversation, request.conversation_id)
            if not conversation or conversation.user_id != user_id:
                raise HTTPException(status_code=404, detail="对话不存在")
        else:
            conversation = Conversation(
                user_id=user_id,
                title=_truncate_title(request.question),
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)

    # Load conversation history for multi-turn context
    history = _load_history(conversation.id, user_id)

    # Resolve file_ids → stored_filenames for file-scoped search
    stored_filenames = _resolve_stored_filenames(request.file_ids, user_id)

    result = ask_question(
        request.question,
        user_id=user_id,
        history=history,
        stored_filenames=stored_filenames,
        dense_weight=request.dense_weight,
        sparse_weight=request.bm25_weight,
        adaptive=request.adaptive_retrieval,
        include_debug=request.include_retrieval_debug,
    )

    # Persist messages
    with Session(engine) as session:
        conversation = session.get(Conversation, conversation.id)

        user_message = Message(
            user_id=user_id,
            conversation_id=conversation.id,
            role="user",
            content=request.question,
        )
        session.add(user_message)

        assistant_message = Message(
            user_id=user_id,
            conversation_id=conversation.id,
            role="assistant",
            content=result["answer"],
            sources=json.dumps(
                {
                    "files": result["sources"],
                    "citations": result["citations"],
                    "retrieval": result["retrieval"],
                    "debug": result["debug"],
                },
                ensure_ascii=False,
            ),
        )
        session.add(assistant_message)

        conversation.updated_at = datetime.utcnow()
        if conversation.title == "新对话":
            conversation.title = _truncate_title(request.question)
        session.commit()
        session.refresh(conversation)

    return api_success(
        "对话已生成",
        {
            "conversation_id": conversation.id,
            "conversation": {
                "id": conversation.id,
                "title": conversation.title,
            },
            "answer": result["answer"],
            "sources": result["sources"],
            "citations": result["citations"],
            "retrieval": result["retrieval"],
            "debug": result["debug"],
        },
    )


# ---------------------------------------------------------------------------
# GET /conversations
# ---------------------------------------------------------------------------

@router.get("/conversations")
def list_conversations(current_user: dict = Depends(get_current_user)):
    with Session(engine) as session:
        user_id = resolve_current_user_id(current_user, session)

        conversations = session.exec(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        ).all()

        response = []
        for conversation in conversations:
            message_count = session.exec(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.user_id == user_id,
                )
            ).all()

            response.append(
                {
                    "id": conversation.id,
                    "title": conversation.title,
                    "created_at": (
                        conversation.created_at.isoformat()
                        if conversation.created_at
                        else None
                    ),
                    "updated_at": (
                        conversation.updated_at.isoformat()
                        if conversation.updated_at
                        else None
                    ),
                    "message_count": len(message_count),
                }
            )

        return api_success("获取对话列表成功", response)


# ---------------------------------------------------------------------------
# GET /conversations/{id}
# ---------------------------------------------------------------------------

@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
):
    with Session(engine) as session:
        user_id = resolve_current_user_id(current_user, session)

        conversation = session.get(Conversation, conversation_id)
        if not conversation or conversation.user_id != user_id:
            raise HTTPException(status_code=404, detail="对话不存在")

        messages = session.exec(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.user_id == user_id,
            )
            .order_by(Message.created_at.asc())
        ).all()

        return api_success(
            "获取对话详情成功",
            {
                "id": conversation.id,
                "title": conversation.title,
                "created_at": (
                    conversation.created_at.isoformat()
                    if conversation.created_at
                    else None
                ),
                "updated_at": (
                    conversation.updated_at.isoformat()
                    if conversation.updated_at
                    else None
                ),
                "messages": [_serialize_message(message) for message in messages],
            },
        )


# ---------------------------------------------------------------------------
# DELETE /conversations/{id}
# ---------------------------------------------------------------------------

@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
):
    with Session(engine) as session:
        user_id = resolve_current_user_id(current_user, session)

        conversation = session.get(Conversation, conversation_id)
        if not conversation or conversation.user_id != user_id:
            raise HTTPException(status_code=404, detail="对话不存在")

        session.exec(
            delete(Message).where(
                Message.conversation_id == conversation_id,
                Message.user_id == user_id,
            )
        )
        session.delete(conversation)
        session.commit()

    return api_success("对话已删除", None)


# ---------------------------------------------------------------------------
# GET /conversations/{id}/export
# ---------------------------------------------------------------------------

@router.get("/conversations/{conversation_id}/export")
def export_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
):
    with Session(engine) as session:
        user_id = resolve_current_user_id(current_user, session)

        conversation = session.get(Conversation, conversation_id)
        if not conversation or conversation.user_id != user_id:
            raise HTTPException(status_code=404, detail="对话不存在")

        messages = session.exec(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.user_id == user_id,
            )
            .order_by(Message.created_at.asc())
        ).all()

        payload = {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "messages": [_serialize_message(message) for message in messages],
        }

    filename = f"conversation-{conversation_id}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
