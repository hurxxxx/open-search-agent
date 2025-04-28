from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from typing import Any, List, Optional

from app.core.config import settings
from app.core.security import create_access_token
from app.models.schemas import Token, SearchQuery, AgentResponse
from app.api.dependencies import get_agent_service, get_current_user
from app.services.agent_service import AgentService

router = APIRouter()

# Authentication endpoints
@router.post("/auth/login", response_model=Token)
async def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    # In a real application, you would validate the username and password
    # against a database. For this example, we'll accept any username/password
    # combination in debug mode, or a fixed set in production.

    if settings.DEBUG:
        # In debug mode, accept any credentials
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            subject=form_data.username, expires_delta=access_token_expires
        )
        return {
            "access_token": access_token,
            "token_type": "bearer"
        }
    else:
        # In production, you would validate against a database
        # For this example, we'll accept a fixed set of credentials
        if form_data.username == "admin" and form_data.password == "password":
            access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            access_token = create_access_token(
                subject=form_data.username, expires_delta=access_token_expires
            )
            return {
                "access_token": access_token,
                "token_type": "bearer"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

# Search agent endpoints
@router.post("/search", response_model=AgentResponse)
async def search(
    query: SearchQuery,
    agent_service: AgentService = Depends(get_agent_service),
    current_user: str = Depends(get_current_user),
    x_search_provider: str = Header(None)
) -> Any:
    """
    Process a search query through the AI agent

    Optionally accepts X-Search-Provider header to override the default search provider
    """
    # Override the search provider if specified in the header
    search_provider_override = None
    if x_search_provider:
        # Validate the search provider
        valid_providers = ["duckduckgo", "google", "searxng", "tavily", "serper", "brave"]
        if x_search_provider.lower() in valid_providers:
            search_provider_override = x_search_provider.lower()

    response = await agent_service.process_prompt(query.prompt, search_provider_override)
    return response

# Public endpoints (no authentication required)
@router.get("/health")
async def health_check() -> dict:
    """
    Health check endpoint
    """
    return {"status": "ok"}
