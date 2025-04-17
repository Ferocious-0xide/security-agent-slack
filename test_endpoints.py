import os
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone
import uuid
from mock_charlotte import app
from dotenv import load_dotenv
from unittest.mock import patch, MagicMock

# Load environment variables
load_dotenv()

# Initialize test client
client = TestClient(app)

# Test configuration
TEST_API_KEY = os.getenv("CHARLOTTE_SERVICE_KEY")
HEADERS = {"Authorization": f"Bearer {TEST_API_KEY}"}
SLACK_HEADERS = {
    "X-Slack-Signature": "test_signature",
    "X-Slack-Request-Timestamp": str(int(datetime.now(timezone.utc).timestamp()))
}

# Mock OpenAI responses
mock_embedding_response = MagicMock()
mock_embedding_response.data = [MagicMock(embedding=[0.1] * 1536)]

mock_completion_response = MagicMock()
mock_completion_response.choices = [MagicMock(message=MagicMock(content="Test response"))]

# Test data
test_query = {
    "query": "What are common indicators of ransomware?",
    "max_tokens": 500
}

test_slack_event = {
    "type": "event_callback",
    "event": {
        "type": "message",
        "text": "What are common indicators of ransomware?",
        "user": "U123456",
        "channel": "C123456"
    },
    "team_id": "T123456",
    "api_app_id": "A123456",
    "event_id": "Ev123456",
    "event_time": int(datetime.now(timezone.utc).timestamp())
}

test_incident = {
    "salesforce_id": str(uuid.uuid4()),
    "title": "Suspicious Network Activity",
    "description": "Multiple failed login attempts detected",
    "severity": "high",
    "status": "open",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "updated_at": datetime.now(timezone.utc).isoformat()
}

# Test chat completions endpoint
@patch('mock_charlotte.openai_client.embeddings.create', return_value=mock_embedding_response)
@patch('mock_charlotte.openai_client.chat.completions.create', return_value=mock_completion_response)
def test_chat_completions_unauthorized(mock_completion, mock_embedding):
    response = client.post("/v1/chat/completions", json=test_query)
    assert response.status_code == 401
    assert "Invalid or missing API key" in response.json()["detail"]

@patch('mock_charlotte.openai_client.embeddings.create', return_value=mock_embedding_response)
@patch('mock_charlotte.openai_client.chat.completions.create', return_value=mock_completion_response)
def test_chat_completions_authorized(mock_completion, mock_embedding):
    response = client.post("/v1/chat/completions", json=test_query, headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "confidence" in data
    assert "sources" in data
    assert "timestamp" in data

@patch('mock_charlotte.openai_client.embeddings.create', return_value=mock_embedding_response)
@patch('mock_charlotte.openai_client.chat.completions.create', return_value=mock_completion_response)
def test_chat_completions_invalid_query(mock_completion, mock_embedding):
    response = client.post("/v1/chat/completions", json={}, headers=HEADERS)
    assert response.status_code == 422

# Test Slack events endpoint
def test_slack_events_unauthorized():
    response = client.post("/v1/slack/events", json=test_slack_event)
    assert response.status_code == 401
    assert "Invalid or missing Slack signature" in response.json()["detail"]

def test_slack_events_url_verification():
    verification_event = {
        "type": "url_verification",
        "challenge": "test_challenge"
    }
    response = client.post("/v1/slack/events", json=verification_event, headers=SLACK_HEADERS)
    assert response.status_code == 200
    assert response.json()["challenge"] == "test_challenge"

@patch('mock_charlotte.openai_client.embeddings.create', return_value=mock_embedding_response)
@patch('mock_charlotte.openai_client.chat.completions.create', return_value=mock_completion_response)
def test_slack_events_message(mock_completion, mock_embedding):
    response = client.post("/v1/slack/events", json=test_slack_event, headers=SLACK_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "blocks" in data

# Test Salesforce incidents endpoints
def test_create_incident_unauthorized():
    response = client.post("/v1/salesforce/incidents", json=test_incident)
    assert response.status_code == 401
    assert "Invalid or missing API key" in response.json()["detail"]

def test_create_incident_authorized():
    response = client.post("/v1/salesforce/incidents", json=test_incident, headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["status"] == "success"

def test_get_incident_unauthorized():
    response = client.get(f"/v1/salesforce/incidents/{test_incident['salesforce_id']}")
    assert response.status_code == 401
    assert "Invalid or missing API key" in response.json()["detail"]

def test_get_incident_not_found():
    response = client.get("/v1/salesforce/incidents/nonexistent-id", headers=HEADERS)
    assert response.status_code == 404
    assert "Incident not found" in response.json()["detail"]

def test_get_incident_authorized():
    # First create an incident
    create_response = client.post("/v1/salesforce/incidents", json=test_incident, headers=HEADERS)
    assert create_response.status_code == 200
    
    # Then retrieve it
    response = client.get(f"/v1/salesforce/incidents/{test_incident['salesforce_id']}", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["salesforce_id"] == test_incident["salesforce_id"]
    assert data["title"] == test_incident["title"]
    assert data["severity"] == test_incident["severity"]

# Test status endpoints
def test_get_status():
    response = client.get("/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert "components" in data
    assert len(data["components"]) > 0
    for component in data["components"]:
        assert "component" in component
        assert "status" in component
        assert "last_updated" in component

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "timestamp" in data
    assert "version" in data
    assert "components" in data
    assert data["version"] == "1.0.0"
    assert data["status"] in ["healthy", "degraded", "unhealthy"]

# Test error handling
def test_invalid_json():
    response = client.post("/v1/chat/completions", data="invalid json", headers=HEADERS)
    assert response.status_code == 422

def test_invalid_api_key():
    headers = {"Authorization": "Bearer invalid_key"}
    response = client.post("/v1/chat/completions", json=test_query, headers=headers)
    assert response.status_code == 401

if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 