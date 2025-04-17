import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from slack_handler import SlackHandler
from security_agent import SecurityAgent
import os

@pytest.fixture
def mock_security_agent():
    return AsyncMock(spec=SecurityAgent)

@pytest.fixture
def slack_handler(mock_security_agent):
    with patch.dict(os.environ, {
        'SLACK_BOT_TOKEN': 'test_token',
        'SLACK_APP_TOKEN': 'test_app_token',
        'SLACK_SIGNING_SECRET': 'test_secret'
    }):
        return SlackHandler(mock_security_agent)

@pytest.mark.asyncio
async def test_handle_security_command(slack_handler, mock_security_agent):
    # Mock the ack and say functions
    ack = AsyncMock()
    say = AsyncMock()
    
    # Test search command
    command = {
        "command": "/security",
        "text": "search test query",
        "user_id": "U123456"
    }
    
    mock_security_agent.process_slack_command.return_value = {
        "status": "success",
        "results": [
            {"title": "Test Result", "content": "Test content"}
        ]
    }
    
    await slack_handler.handle_security_command(command, ack, say)
    
    # Verify ack was called
    ack.assert_called_once()
    
    # Verify say was called with blocks
    say.assert_called_once()
    assert "blocks" in say.call_args[1]

@pytest.mark.asyncio
async def test_handle_message(slack_handler, mock_security_agent):
    # Mock the say function
    say = AsyncMock()
    
    # Test message with security keyword
    event = {
        "type": "message",
        "text": "security alert test",
        "channel": "C123456",
        "user": "U123456"
    }
    
    mock_security_agent.process_slack_event.return_value = {
        "status": "success",
        "results": [
            {"title": "Test Result", "content": "Test content"}
        ]
    }
    
    await slack_handler.handle_message(event, say)
    
    # Verify say was called with blocks
    say.assert_called_once()
    assert "blocks" in say.call_args[1]

@pytest.mark.asyncio
async def test_handle_app_mention(slack_handler, mock_security_agent):
    # Mock the say function and WebClient
    say = AsyncMock()
    slack_handler.client.auth_test = MagicMock(return_value={"user_id": "BOT123"})
    
    # Test app mention
    event = {
        "type": "app_mention",
        "text": "<@BOT123> search test",
        "channel": "C123456"
    }
    
    mock_security_agent.query_knowledge_base.return_value = [
        {"title": "Test Result", "content": "Test content"}
    ]
    
    await slack_handler.handle_app_mention(event, say)
    
    # Verify say was called with blocks
    say.assert_called_once()
    assert "blocks" in say.call_args[1]

@pytest.mark.asyncio
async def test_handle_incident_status(slack_handler, mock_security_agent):
    # Mock the ack and say functions
    ack = AsyncMock()
    say = AsyncMock()
    
    # Test incident status update
    body = {
        "actions": [{
            "value": "123",
            "selected_option": {
                "value": "in_progress"
            }
        }]
    }
    
    mock_security_agent.trigger_workflow.return_value = {
        "status": "success",
        "workflow_id": "wf_123",
        "incident_status": "in_progress"
    }
    
    await slack_handler.handle_incident_status(ack, body, say)
    
    # Verify ack was called
    ack.assert_called_once()
    
    # Verify say was called with success message
    say.assert_called_once()
    assert "in_progress" in say.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_knowledge_search(slack_handler, mock_security_agent):
    # Mock the ack and say functions
    ack = AsyncMock()
    say = AsyncMock()
    
    # Test knowledge search
    body = {
        "actions": [{
            "value": "test query"
        }]
    }
    
    mock_security_agent.query_knowledge_base.return_value = [
        {"title": "Test Result", "content": "Test content"}
    ]
    
    await slack_handler.handle_knowledge_search(ack, body, say)
    
    # Verify ack was called
    ack.assert_called_once()
    
    # Verify say was called with blocks
    say.assert_called_once()
    assert "blocks" in say.call_args[1] 