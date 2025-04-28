from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import ValidationError

from app.core.config import settings
from app.core.security import TokenData
from app.services.agent_service import AgentService
from app.services.llm_service import LLMService
from app.services.search_service import SearchService

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

# Dependency to get the current user from the token
async def get_current_user(token: str = Depends(oauth2_scheme)) -> Optional[str]:
    """
    Validate access token and return the username
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except (JWTError, ValidationError):
        raise credentials_exception
    
    return token_data.username

# Service dependencies
def get_agent_service() -> AgentService:
    return AgentService()

def get_llm_service() -> LLMService:
    return LLMService()

def get_search_service() -> SearchService:
    return SearchService()
