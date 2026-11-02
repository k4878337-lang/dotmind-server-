import json
import os
import re
import uuid
import base64
import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.agent import AgentProfile
from app.schemas.chat import (
    ConversationCreate,
    ConversationOut,
    ConversationDetail,
    MessageCreate,
    MessageOut,
    AttachmentUploadRequest,
    AttachmentUploadResponse,
    AttachmentPayload
)
from app.services.llm.gemini import GeminiProvider
from app.services.llm.router import llm_router
from app.services.memory_service import memory_service

router = APIRouter(prefix="/chat", tags=["Chat & Conversations"])

UPLOAD_DIR = os.path.join(settings.WORKSPACE_ROOT, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload", response_model=AttachmentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    payload: AttachmentUploadRequest,
    current_user: User = Depends(get_current_user)
):
    raw_filename = payload.filename or "attachment"
    clean_filename = os.path.basename(raw_filename)
    clean_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', clean_filename)
    if not clean_filename:
        clean_filename = "attachment"

    try:
        raw_b64 = payload.base64_data
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        content = base64.b64decode(raw_b64)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 payload."
        )

    # Enforce 25MB limit
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds the 25MB maximum limit."
        )

    file_id = str(uuid.uuid4())
    user_upload_dir = os.path.join(UPLOAD_DIR, current_user.id, file_id)
    os.makedirs(user_upload_dir, exist_ok=True)
    target_path = os.path.join(user_upload_dir, clean_filename)

    with open(target_path, "wb") as f:
        f.write(content)

    mime_type = payload.mime_type or "application/octet-stream"
    file_url = f"/api/v1/chat/files/{file_id}/{clean_filename}"

    return AttachmentUploadResponse(
        id=file_id,
        filename=clean_filename,
        mime_type=mime_type,
        size_bytes=len(content),
        file_url=file_url,
        base64_data=payload.base64_data
    )

@router.get("/files/{file_id}/{filename}")
async def get_uploaded_file(
    file_id: str,
    filename: str,
    current_user: User = Depends(get_current_user)
):
    clean_filename = os.path.basename(filename)
    expected_path = os.path.realpath(os.path.join(UPLOAD_DIR, current_user.id, file_id, clean_filename))
    base_user_dir = os.path.realpath(os.path.join(UPLOAD_DIR, current_user.id))

    if not expected_path.startswith(base_user_dir) or not os.path.exists(expected_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found or access denied."
        )

    return FileResponse(expected_path, filename=clean_filename)

@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    conv = Conversation(
        user_id=current_user.id,
        title=payload.title or "New Conversation"
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut.from_orm(conv)

@router.get("/conversations", response_model=List[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return [ConversationOut.from_orm(c) for c in result.scalars().all()]

@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id, Conversation.user_id == current_user.id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )
    return ConversationDetail.from_orm(conv)

@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found."
        )
    await db.delete(conv)
    await db.commit()
    return None

@router.post("/conversations/{conversation_id}/messages")
async def send_message_stream(
    conversation_id: str,
    payload: MessageCreate,
    x_gemini_api_key: Optional[str] = Header(None, alias="X-Gemini-Api-Key"),
    x_gemini_model: Optional[str] = Header(None, alias="X-Gemini-Model"),
    x_ai_provider: Optional[str] = Header(None, alias="X-Ai-Provider"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify ownership
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or unauthorized access."
        )

    # 1. Save User Message (or deduplicate if retrying a failed turn)
    attachments_json = None
    if payload.attachments:
        attachments_json = json.dumps([a.dict() for a in payload.attachments])

    # Check if this is a retry of the immediately preceding failed/error message
    last_msgs_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(2)
    )
    last_msgs = list(last_msgs_res.scalars().all())

    reusing_turn = False
    if len(last_msgs) >= 2:
        last_asst, last_user = last_msgs[0], last_msgs[1]
        if (
            last_asst.role == "assistant"
            and last_asst.status in ["error", "cancelled", "failed"]
            and last_user.role == "user"
            and last_user.content == payload.content
        ):
            user_msg = last_user
            assistant_msg = last_asst
            assistant_msg.status = "streaming"
            assistant_msg.content = ""
            reusing_turn = True
            await db.commit()
            await db.refresh(assistant_msg)
    elif len(last_msgs) == 1 and last_msgs[0].role == "user" and last_msgs[0].content == payload.content:
        user_msg = last_msgs[0]
        assistant_msg = Message(
            conversation_id=conversation_id,
            user_id=current_user.id,
            role="assistant",
            content="",
            status="streaming"
        )
        db.add(assistant_msg)
        reusing_turn = True
        await db.commit()
        await db.refresh(assistant_msg)

    if not reusing_turn:
        user_msg = Message(
            conversation_id=conversation_id,
            user_id=current_user.id,
            role="user",
            content=payload.content,
            attachments=attachments_json,
            status="completed"
        )
        db.add(user_msg)
        
        # Auto-update conversation title if it's default
        if conv.title == "New Conversation":
            conv.title = payload.content[:40] + ("..." if len(payload.content) > 40 else "")

        # 2. Pre-create Assistant Message record
        assistant_msg = Message(
            conversation_id=conversation_id,
            user_id=current_user.id,
            role="assistant",
            content="",
            status="streaming"
        )
        db.add(assistant_msg)
        await db.commit()
        await db.refresh(assistant_msg)

    # 3. Retrieve Agent Profile
    agent_res = await db.execute(
        select(AgentProfile).where(AgentProfile.user_id == current_user.id)
    )
    agent_prof = agent_res.scalar_one_or_none()
    system_instruction = agent_prof.instructions if agent_prof else "You are DotMind."

    # 3b. Retrieve & Inject Relevant Persistent Memory Context
    memory_context = await memory_service.format_memory_context(db, current_user.id, payload.content)
    if memory_context:
        system_instruction = f"{system_instruction}\n\n{memory_context}"

    # 4. Fetch prior history
    history_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    all_msgs = history_res.scalars().all()
    formatted_history = [
        {"role": m.role, "content": m.content}
        for m in all_msgs if m.role in ["user", "assistant"] and m.content
    ]

    # Generator for SSE using the request's database session
    async def event_generator():
        accumulated_text = []
        accumulated_deltas = []
        assistant_id = assistant_msg.id
        work_log_data = None
        has_error = False

        yield {
            "event": "start",
            "data": json.dumps({
                "message_id": assistant_id,
                "conversation_id": conversation_id,
                "role": "assistant"
            })
        }

        try:
            from app.services.agent.orchestrator import agent_orchestrator
            async for agent_event in agent_orchestrator.run_agent_loop(
                db=db,
                user_id=current_user.id,
                conversation_id=conversation_id,
                user_message=payload.content,
                base_instructions=system_instruction,
                personal_api_key=x_gemini_api_key,
                selected_model=x_gemini_model,
                attachments=payload.attachments
            ):
                evt_name = agent_event.get("event")
                evt_data = agent_event.get("data")
                if evt_name == "token":
                    try:
                        token_dict = json.loads(evt_data)
                        accumulated_text.append(token_dict.get("token", ""))
                    except Exception:
                        pass
                elif evt_name == "answer_delta":
                    try:
                        delta_dict = json.loads(evt_data)
                        accumulated_deltas.append(delta_dict.get("delta", ""))
                    except Exception:
                        pass
                elif evt_name == "error":
                    has_error = True
                elif evt_name == "complete":
                    try:
                        comp_dict = json.loads(evt_data)
                        work_log_data = comp_dict.get("work_log")
                    except Exception:
                        pass

                # Enrich data with conversation_id and message_id
                try:
                    if isinstance(evt_data, str):
                        data_obj = json.loads(evt_data)
                    elif isinstance(evt_data, dict):
                        data_obj = dict(evt_data)
                    else:
                        data_obj = {}
                    data_obj.setdefault("conversation_id", conversation_id)
                    data_obj.setdefault("message_id", assistant_id)
                    agent_event["data"] = json.dumps(data_obj)
                except Exception:
                    pass

                yield agent_event

            final_content = "".join(accumulated_text) if accumulated_text else "".join(accumulated_deltas)
            assistant_msg.content = final_content
            if work_log_data:
                assistant_msg.tool_calls = json.dumps(work_log_data)
            assistant_msg.status = "error" if has_error else "completed"
            await db.commit()

            yield {
                "event": "done",
                "data": json.dumps({
                    "message_id": assistant_id,
                    "conversation_id": conversation_id,
                    "content": final_content,
                    "work_log": work_log_data,
                    "status": assistant_msg.status
                })
            }
        except asyncio.CancelledError:
            try:
                assistant_msg.content = "".join(accumulated_text) + " [Cancelled by client]"
                assistant_msg.status = "cancelled"
                await db.commit()
            except Exception:
                pass
            raise
        except Exception as ex:
            error_msg = f"Error during streaming: {str(ex)}"
            try:
                assistant_msg.content = error_msg
                assistant_msg.status = "error"
                await db.commit()
            except Exception:
                pass
            yield {
                "event": "error",
                "data": json.dumps({
                    "message_id": assistant_id,
                    "conversation_id": conversation_id,
                    "error": error_msg
                })
            }

    return EventSourceResponse(event_generator())
