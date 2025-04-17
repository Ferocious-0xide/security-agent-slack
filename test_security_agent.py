import pytest
import os
from security_agent import SecurityAgent
from unittest.mock import patch, MagicMock

@pytest.fixture
def security_agent():
    with patch.dict(os.environ, {
        'SLACK_BOT_TOKEN': 'test_token',
        'SLACK_APP_TOKEN': 'test_app_token',
        'SLACK_SIGNING_SECRET': 'test_secret',
        'OPENAI_API_KEY': 'test_key',
        'DATABASE_URL': 'test_db_url'
    }):
        return SecurityAgent()

@pytest.mark.asyncio
async def test_process_slack_command(security_agent):
    command = {
        "command": "/security",
        "text": "check status",
        "user_id": "U123456"
    }
    result = await security_agent.process_slack_command(command)
    assert result["status"] == "success"

@pytest.mark.asyncio
async def test_process_slack_event(security_agent):
    event = {
        "type": "message",
        "text": "security alert",
        "channel": "C123456"
    }
    result = await security_agent.process_slack_event(event)
    assert result["status"] == "success"

@pytest.mark.asyncio
async def test_query_knowledge_base(security_agent):
    query = "How to handle a security breach?"
    result = await security_agent.query_knowledge_base(query)
    assert isinstance(result, list)

@pytest.mark.asyncio
async def test_create_incident(security_agent):
    incident_data = {
        "title": "Security Breach",
        "description": "Unauthorized access detected",
        "severity": "high"
    }
    result = await security_agent.create_incident(incident_data)
    assert result["status"] == "success"
    assert "incident_id" in result

@pytest.mark.asyncio
async def test_trigger_workflow(security_agent):
    workflow_data = {
        "type": "incident_response",
        "parameters": {
            "action": "isolate_network"
        }
    }
    result = await security_agent.trigger_workflow(workflow_data)
    assert result["status"] == "success"
    assert "workflow_id" in result

def test_missing_environment_variables():
    with pytest.raises(EnvironmentError):
        SecurityAgent() 