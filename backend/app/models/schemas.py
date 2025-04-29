from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    prompt: str = Field(..., description="User prompt to be processed by the search agent")


class SearchResult(BaseModel):
    title: str
    link: str
    snippet: str


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]


class DecomposedQuery(BaseModel):
    original_prompt: str
    search_queries: List[str]


class AgentSearchStep(BaseModel):
    query: str
    results: List[SearchResult]
    sufficient: bool
    reasoning: str


class AgentResponse(BaseModel):
    original_prompt: str
    search_steps: List[AgentSearchStep]
    final_report: str
    sources: List[Dict[str, Any]]


class StreamingSearchResponse(BaseModel):
    """Model for streaming search responses"""
    event: str  # Event type: "search_start", "search_query", "search_results", "report_chunk", "search_complete"
    data: Dict[str, Any]  # Event-specific data


class SearchResultsResponse(BaseModel):
    """Model for search results only (without final report)"""
    original_prompt: str
    search_steps: List[AgentSearchStep]
    sources: List[Dict[str, Any]]
