from fastapi import APIRouter, Depends, Header
from typing import Any, Optional

from app.models.schemas import SearchQuery, AgentResponse
from app.api.dependencies import get_agent_service, get_auth
from app.services.agent_service import AgentService

router = APIRouter()

# Health check endpoint
@router.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint - does not require authentication
    """
    return {"status": "ok"}

# Search agent endpoints
@router.post("/search", response_model=AgentResponse)
async def search(
    query: SearchQuery,
    agent_service: AgentService = Depends(get_agent_service),
    current_user: str = Depends(get_auth),  # Use Bearer token authentication
    x_search_provider: Optional[str] = Header(None)
) -> Any:
    """
    Process a search query through the AI agent

    Optionally accepts X-Search-Provider header to override the default search provider
    Requires Bearer token authentication with the API key
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
