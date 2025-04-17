from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from typing import Dict, Any, Optional
import logging
import os
from dotenv import load_dotenv
from security_agent import SecurityAgent
import asyncio
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SlackHandler:
    def __init__(self):
        load_dotenv()
        self.app = App(token=os.getenv("SLACK_BOT_TOKEN"))
        self.security_agent = SecurityAgent()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup Slack command and event handlers."""
        # Command handlers
        self.app.command("/security")(self.handle_security_command)
        
        # Event handlers
        self.app.event("message")(self.handle_message)
        self.app.event("app_mention")(self.handle_app_mention)
        
        # Action handlers
        self.app.action("incident_status")(self.handle_incident_status)
        self.app.action("knowledge_search")(self.handle_knowledge_search)
    
    def handle_security_command(self, ack, command, say):
        """Handle /security command."""
        ack()  # Acknowledge command immediately
        
        try:
            # Run async operation in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            response = loop.run_until_complete(
                self.security_agent.process_slack_command(command["command"], command["text"])
            )
            loop.close()
            
            if "error" in response:
                say(f"Error: {response['error']}")
            elif "success" in response:
                if "results" in response:
                    for result in response["results"]:
                        say(f"*{result['title']}*\n{result['content']}")
                elif "incident_id" in response:
                    say(f"Incident created with ID: {response['incident_id']}")
                elif "response" in response:
                    say(response["response"])
        except Exception as e:
            logger.error(f"Error handling security command: {str(e)}")
            say(f"Error processing command: {str(e)}")
    
    def handle_message(self, event, say):
        """Handle message events."""
        try:
            # Run async operation in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            response = loop.run_until_complete(
                self.security_agent.process_slack_event(event)
            )
            loop.close()
            
            if response.get("status") == "success" and "results" in response:
                for result in response["results"]:
                    say(f"*{result['title']}*\n{result['content']}")
        except Exception as e:
            logger.error(f"Error handling message: {str(e)}")
    
    def handle_app_mention(self, event, say):
        """Handle app mention events."""
        try:
            # Run async operation in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            response = loop.run_until_complete(
                self.security_agent.process_slack_event(event)
            )
            loop.close()
            
            if response.get("status") == "success" and "results" in response:
                for result in response["results"]:
                    say(f"*{result['title']}*\n{result['content']}")
        except Exception as e:
            logger.error(f"Error handling app mention: {str(e)}")
    
    def handle_incident_status(self, ack, body, say):
        """Handle incident status actions."""
        ack()  # Acknowledge action immediately
        
        try:
            incident_id = body["actions"][0]["value"]
            # Run async operation in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            incident = loop.run_until_complete(
                self.security_agent.db.get_incident(incident_id)
            )
            loop.close()
            
            if incident:
                say(f"Incident Status: {incident.status}")
            else:
                say("Incident not found")
        except Exception as e:
            logger.error(f"Error handling incident status: {str(e)}")
            say(f"Error checking incident status: {str(e)}")
    
    def handle_knowledge_search(self, ack, body, say):
        """Handle knowledge search actions."""
        ack()  # Acknowledge action immediately
        
        try:
            query = body["actions"][0]["value"]
            # Run async operation in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(
                self.security_agent.db.search_knowledge(query)
            )
            loop.close()
            
            if results:
                for result in results:
                    say(f"*{result.title}*\n{result.content}")
            else:
                say("No results found")
        except Exception as e:
            logger.error(f"Error handling knowledge search: {str(e)}")
            say(f"Error searching knowledge: {str(e)}")
    
    def start(self):
        """Start the Slack app in socket mode."""
        handler = SocketModeHandler(self.app, os.getenv("SLACK_APP_TOKEN"))
        handler.start() 