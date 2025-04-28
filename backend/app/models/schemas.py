from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    is_active: bool = True

    class Config:
        orm_mode = True


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
