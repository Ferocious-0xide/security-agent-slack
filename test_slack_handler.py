import unittest
from unittest.mock import MagicMock, patch
from slack_handler import SlackHandler
from security_agent import SecurityAgent
import os

class TestSlackHandler(unittest.TestCase):
    def setUp(self):
        # Mock environment variables
        self.env_patcher = patch.dict(os.environ, {
            'SLACK_APP_TOKEN': 'test_token',
            'SLACK_SIGNING_SECRET': 'test_secret'
        })
        self.env_patcher.start()
        
        # Initialize handler with mocked security agent
        self.security_agent = MagicMock(spec=SecurityAgent)
        self.handler = SlackHandler(self.security_agent)
    
    def tearDown(self):
        self.env_patcher.stop()
    
    def test_handle_security_command(self):
        # Mock command body
        body = {
            "text": "search test",
            "channel_id": "C123",
            "response_url": "https://hooks.slack.com/commands/123/456"
        }
        
        # Mock security agent response
        self.security_agent.process_command.return_value = {
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Test result"}}]
        }
        
        # Mock ack function
        ack = MagicMock()
        
        # Call handler
        self.handler.handle_security_command(ack, body, MagicMock())
        
        # Verify ack was called
        ack.assert_called_once()
        
        # Verify security agent was called with correct command
        self.security_agent.process_command.assert_called_once_with("search test")
    
    def test_handle_message(self):
        # Mock event
        event = {
            "type": "message",
            "text": "security test",
            "channel": "C123"
        }
        
        # Mock security agent response
        self.security_agent.process_slack_event.return_value = {
            "status": "success",
            "results": [{"title": "Test", "content": "Test content"}]
        }
        
        # Mock say function
        say = MagicMock()
        
        # Call handler
        self.handler.handle_message(event, say)
        
        # Verify security agent was called
        self.security_agent.process_slack_event.assert_called_once()
    
    def test_handle_app_mention(self):
        # Mock event
        event = {
            "type": "app_mention",
            "text": "<@APP123> search test",
            "channel": "C123"
        }
        
        # Mock client auth test
        self.handler.client.auth_test = MagicMock(return_value={"user_id": "APP123"})
        
        # Mock security agent response
        self.security_agent.query_knowledge_base.return_value = [
            {"title": "Test", "content": "Test content"}
        ]
        
        # Mock say function
        say = MagicMock()
        
        # Call handler
        self.handler.handle_app_mention(event, say)
        
        # Verify security agent was called with correct query
        self.security_agent.query_knowledge_base.assert_called_once_with("search test")
    
    def test_handle_incident_status(self):
        # Mock body
        body = {
            "actions": [{
                "value": "123",
                "selected_option": {"value": "in_progress"}
            }]
        }
        
        # Mock security agent response
        self.security_agent.trigger_workflow.return_value = {
            "status": "success"
        }
        
        # Mock ack and say functions
        ack = MagicMock()
        say = MagicMock()
        
        # Call handler
        self.handler.handle_incident_status(ack, body, say)
        
        # Verify ack was called
        ack.assert_called_once()
        
        # Verify security agent was called with correct data
        self.security_agent.trigger_workflow.assert_called_once_with({
            "incident_id": "123",
            "status": "in_progress"
        })
    
    def test_handle_knowledge_search(self):
        # Mock body
        body = {
            "actions": [{
                "value": "test query"
            }]
        }
        
        # Mock security agent response
        self.security_agent.query_knowledge_base.return_value = [
            {"title": "Test", "content": "Test content"}
        ]
        
        # Mock ack and say functions
        ack = MagicMock()
        say = MagicMock()
        
        # Call handler
        self.handler.handle_knowledge_search(ack, body, say)
        
        # Verify ack was called
        ack.assert_called_once()
        
        # Verify security agent was called with correct query
        self.security_agent.query_knowledge_base.assert_called_once_with("test query")

if __name__ == '__main__':
    unittest.main() 