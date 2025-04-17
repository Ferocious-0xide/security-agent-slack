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
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SlackHandler:
    def __init__(self, security_agent: SecurityAgent):
        load_dotenv()
        self.security_agent = security_agent
        
        # Initialize Slack app
        self.app = App(
            token=os.getenv('SLACK_BOT_TOKEN'),
            signing_secret=os.getenv('SLACK_SIGNING_SECRET')
        )
        
        # Initialize WebClient for API calls
        self.client = WebClient(token=os.getenv('SLACK_BOT_TOKEN'))
        
        # Register event handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Register all Slack event and command handlers."""
        try:
            # Command handlers
            self.app.command("/security")(self.handle_security_command)
            
            # Event handlers
            self.app.event("message")(self.handle_message)
            self.app.event("app_mention")(self.handle_app_mention)
            
            # Action handlers
            self.app.action("incident_status")(self.handle_incident_status)
            self.app.action("knowledge_search")(self.handle_knowledge_search)
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def handle_security_command(self, command: Dict[str, Any], ack, say):
        """Handle the /security slash command."""
        try:
            # Acknowledge the command immediately
            ack()
            
            # Run the async operation in a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self.security_agent.process_slack_command(command)
                )
                
                if result["status"] == "success":
                    if "results" in result:
                        # Format search results
                        blocks = self._format_search_results(result["results"])
                        loop.run_until_complete(say(blocks=blocks))
                    else:
                        loop.run_until_complete(say(result["message"]))
                else:
                    loop.run_until_complete(say(f"Error: {result['message']}"))
            except Exception as e:
                logger.error(f"Error in event loop: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                loop.run_until_complete(say("An error occurred while processing your command."))
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error handling security command: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def handle_message(self, event: Dict[str, Any], say):
        """Handle incoming messages."""
        # Skip messages from bots
        if event.get('subtype') == 'bot_message':
            return
        
        # Run the async operation in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                self.security_agent.process_slack_event(event)
            )
            
            if result["status"] == "success" and "results" in result:
                blocks = self._format_search_results(result["results"])
                loop.run_until_complete(say(blocks=blocks))
        except Exception as e:
            logger.error(f"Error handling message: {str(e)}")
        finally:
            loop.close()
    
    def handle_app_mention(self, event: Dict[str, Any], say):
        """Handle when the bot is mentioned."""
        # Run the async operation in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            text = event.get('text', '').replace(f"<@{self.client.auth_test()['user_id']}>", "").strip()
            if text:
                result = loop.run_until_complete(
                    self.security_agent.query_knowledge_base(text)
                )
                if result:
                    blocks = self._format_search_results(result)
                    loop.run_until_complete(say(blocks=blocks))
        except Exception as e:
            logger.error(f"Error handling app mention: {str(e)}")
            loop.run_until_complete(say("I encountered an error while processing your request."))
        finally:
            loop.close()
    
    def handle_incident_status(self, ack, body, say):
        """Handle incident status updates."""
        # Acknowledge the action immediately
        ack()
        
        # Run the async operation in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            incident_id = body['actions'][0]['value']
            status = body['actions'][0]['selected_option']['value']
            
            result = loop.run_until_complete(
                self.security_agent.trigger_workflow({
                    "incident_id": incident_id,
                    "status": status
                })
            )
            
            if result["status"] == "success":
                loop.run_until_complete(say(f"Incident status updated to: {status}"))
            else:
                loop.run_until_complete(say(f"Error updating incident status: {result['message']}"))
        except Exception as e:
            logger.error(f"Error handling incident status: {str(e)}")
            loop.run_until_complete(say("An error occurred while updating the incident status."))
        finally:
            loop.close()
    
    def handle_knowledge_search(self, ack, body, say):
        """Handle knowledge search actions."""
        # Acknowledge the action immediately
        ack()
        
        # Run the async operation in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            query = body['actions'][0]['value']
            results = loop.run_until_complete(
                self.security_agent.query_knowledge_base(query)
            )
            if results:
                blocks = self._format_search_results(results)
                loop.run_until_complete(say(blocks=blocks))
            else:
                loop.run_until_complete(say("No relevant information found."))
        except Exception as e:
            logger.error(f"Error handling knowledge search: {str(e)}")
            loop.run_until_complete(say("An error occurred while searching the knowledge base."))
        finally:
            loop.close()
    
    def _format_search_results(self, results: list) -> list:
        """Format search results into Slack blocks."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Search Results*"
                }
            }
        ]
        
        for result in results:
            blocks.extend([
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{result['title']}*\n{result['content']}"
                    }
                }
            ])
        
        return blocks
    
    def start(self):
        """Start the Slack app in socket mode."""
        handler = SocketModeHandler(self.app, os.getenv('SLACK_APP_TOKEN'))
        handler.start() 