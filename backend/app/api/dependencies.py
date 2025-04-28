from typing import Optional
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings
from app.services.agent_service import AgentService
from app.services.llm_service import LLMService
from app.services.search_service import SearchService

# Simple Bearer token authentication
security = HTTPBearer(auto_error=False)

# Authentication dependency
async def get_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """
    Simple Bearer token authentication
    Returns "api_user" if authenticated
    """
    # In debug mode, allow access without authentication
    if settings.DEBUG:
        return "debug_user"

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if the token matches the API_KEY
    if credentials.credentials != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return "api_user"

# Service dependencies
def get_agent_service() -> AgentService:
    return AgentService()

def get_llm_service() -> LLMService:
    return LLMService()

def get_search_service() -> SearchService:
    return SearchService()
