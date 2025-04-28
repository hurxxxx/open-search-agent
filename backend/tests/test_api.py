import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.models.schemas import AgentResponse, AgentSearchStep

client = TestClient(app)

# Mock data
mock_search_results = [
    {"title": "Test Result 1", "link": "https://example.com/1", "snippet": "This is a test result 1"},
    {"title": "Test Result 2", "link": "https://example.com/2", "snippet": "This is a test result 2"}
]

mock_agent_response = AgentResponse(
    original_prompt="test prompt",
    search_steps=[
        AgentSearchStep(
            query="test query",
            results=mock_search_results,
            sufficient=True,
            reasoning="The results are sufficient"
        )
    ],
    final_report="This is a test report",
    sources=mock_search_results
)

# Test health check endpoint
def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# Test authentication
def test_login():
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "password"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.json()["token_type"] == "bearer"

# Test search endpoint with authentication
@patch("app.api.routes.get_agent_service")
def test_search_with_auth(mock_get_agent_service):
    # Mock the agent service
    mock_agent = MagicMock()
    mock_agent.process_prompt.return_value = mock_agent_response
    mock_get_agent_service.return_value = mock_agent
    
    # Get auth token
    auth_response = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "password"}
    )
    token = auth_response.json()["access_token"]
    
    # Test search endpoint
    response = client.post(
        "/api/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "test prompt"}
    )
    
    assert response.status_code == 200
    assert response.json()["original_prompt"] == "test prompt"
    assert len(response.json()["search_steps"]) == 1
    assert response.json()["final_report"] == "This is a test report"

# Test search endpoint without authentication
def test_search_without_auth():
    response = client.post(
        "/api/v1/search",
        json={"prompt": "test prompt"}
    )
    assert response.status_code == 401
