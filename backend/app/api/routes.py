from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from typing import Any, Optional, AsyncGenerator
import json
import asyncio

from app.models.schemas import SearchQuery, AgentResponse, StreamingSearchResponse, SearchResultsResponse
from app.api.dependencies import get_agent_service, get_auth
from app.services.agent_service import AgentService
from app.core.config import settings

router = APIRouter()

# Health check endpoint
@router.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint - does not require authentication
    """
    return {"status": "ok"}

# Config endpoint to get current search provider
@router.get("/config", tags=["config"])
async def get_config():
    """
    Get current configuration settings - does not require authentication
    """
    return {
        "search_provider": settings.SEARCH_PROVIDER
    }

# Search agent endpoints
@router.post("/search", response_model=AgentResponse)
async def search(
    query: SearchQuery,
    agent_service: AgentService = Depends(get_agent_service),
    current_user: str = Depends(get_auth),  # Use Bearer token authentication
    x_search_provider: Optional[str] = Header(None)
) -> Any:
    """
    Process a search query through the AI agent and generate a complete report

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


@router.post("/search/results", response_model=SearchResultsResponse)
async def search_results_only(
    query: SearchQuery,
    agent_service: AgentService = Depends(get_agent_service),
    current_user: str = Depends(get_auth),  # Use Bearer token authentication
    x_search_provider: Optional[str] = Header(None)
) -> Any:
    """
    Process a search query through the AI agent but return only search results without generating a final report

    This endpoint is optimized for integration with other LLMs that will generate their own reports
    based on the search results. It saves tokens by not generating a redundant report.

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

    # Get search results without generating a final report
    response = await agent_service.process_search_only(query.prompt, search_provider_override)
    return response


@router.post("/search/stream")
async def search_stream(
    query: SearchQuery,
    agent_service: AgentService = Depends(get_agent_service),
    current_user: str = Depends(get_auth),  # Use Bearer token authentication
    x_search_provider: Optional[str] = Header(None)
) -> StreamingResponse:
    """
    Process a search query through the AI agent with streaming response

    Returns a streaming response with real-time updates on the search progress
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

    async def event_generator():
        try:
            # Start the streaming process
            yield json.dumps({
                "event": "search_start",
                "data": {"prompt": query.prompt}
            }) + "\n"

            # Process the prompt with streaming enabled
            async for event in agent_service.process_prompt_stream(query.prompt, search_provider_override):
                yield json.dumps(event) + "\n"

            # Final event to indicate completion
            yield json.dumps({
                "event": "search_complete",
                "data": {"status": "complete"}
            }) + "\n"

        except Exception as e:
            # Send error event
            yield json.dumps({
                "event": "error",
                "data": {"message": str(e)}
            }) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
