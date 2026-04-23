import uuid
import logging
from typing import Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.product_management_agent import AgentFrameworkProductManagementAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# In-memory session store (in production, use Redis or database)
product_management_agent = AgentFrameworkProductManagementAgent()
active_sessions: Dict[str, str] = {}


class ChatMessage(BaseModel):
    """Chat message model"""
    message: str
    session_id: str = None


class ChatResponse(BaseModel):
    """Chat response model"""
    response: str
    session_id: str
    is_complete: bool
    requires_input: bool


@router.post("/message", response_model=ChatResponse)
async def send_message(chat_message: ChatMessage):
    """Send a message to the product management agent and get a response"""
    try:
        # Generate session ID if not provided
        session_id = chat_message.session_id or str(uuid.uuid4())
        
        # Store session
        active_sessions[session_id] = session_id
        
        # Get response from agent
        response = await product_management_agent.invoke(chat_message.message, session_id)
        
        return ChatResponse(
            response=response.get('content', 'No response available'),
            session_id=session_id,
            is_complete=response.get('is_task_complete', False),
            requires_input=response.get('require_user_input', True)
        )
        
    except Exception as e:
        logger.error(f"Error processing chat message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def stream_message(chat_message: ChatMessage):
    """Stream a response from the product management agent"""
    try:
        # Generate session ID if not provided
        session_id = chat_message.session_id or str(uuid.uuid4())
        
        # Store session
        active_sessions[session_id] = session_id
        
        async def generate_response():
            """Generate streaming response"""
            try:
                async for partial in product_management_agent.stream(
                    chat_message.message, session_id
                ):
                    # Format as SSE (Server-Sent Events)
                    content = partial.get('content', '')
                    is_complete = partial.get('is_task_complete', False)
                    requires_input = partial.get('require_user_input', False)
                    
                    response_data = {
                        "content": content,
                        "session_id": session_id,
                        "is_complete": is_complete,
                        "requires_input": requires_input
                    }
                    
                    yield f"data: {response_data}\n\n"
                    
                    if is_complete:
                        break
                        
            except Exception as e:
                logger.error(f"Error in streaming response: {e}")
                yield f'data: { {"error": "{str(e)}"} }\n\n'
        
        return StreamingResponse(
            generate_response(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*"
            }
        )
        
    except Exception as e:
        logger.error(f"Error setting up streaming: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def get_active_sessions():
    """Get list of active chat sessions"""
    return {"active_sessions": list(active_sessions.keys())}


@router.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """Clear a specific chat session"""
    if session_id in active_sessions:
        del active_sessions[session_id]
        return {"message": f"Session {session_id} cleared"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")
