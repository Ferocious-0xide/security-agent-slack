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
import requests

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
            token=os.getenv('SLACK_APP_TOKEN'),
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
            
            logger.info("Successfully registered all handlers")
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def handle_security_command(self, ack, body, logger):
        try:
            # Acknowledge the command immediately
            ack()
            
            # Extract command text from body
            command_text = body.get("text", "").strip()
            response_url = body.get("response_url")
            
            if not response_url:
                logger.error("No response URL provided in command body")
                return
            
            # Process the command
            result = self.security_agent.process_command(command_text)
            
            # Send response using the response URL
            if result.get("blocks"):
                requests.post(
                    response_url,
                    json={"blocks": result["blocks"]}
                )
            else:
                requests.post(
                    response_url,
                    json={"text": result.get("message", "An error occurred while processing your command.")}
                )
                
        except Exception as e:
            logger.error(f"Error handling security command: {str(e)}")
            if response_url:
                requests.post(
                    response_url,
                    json={"text": f"Error: {str(e)}"}
                )
    
    def handle_message(self, event: Dict[str, Any], say):
        """Handle incoming messages."""
        # Skip messages from other apps
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
        """Handle when the app is mentioned."""
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
                    "text": "*Security Knowledge Results* 🔍"
                }
            }
        ]
        
        for result in results:
            # Add knowledge article section
            blocks.extend([
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Knowledge Article:*\n*{result['title']}*\n{result['content']}"
                    }
                }
            ])
            
            # Add Claude's guidance if present
            if 'guidance' in result:
                # Split the guidance into sections
                guidance_sections = result['guidance'].split('\n## ')
                formatted_guidance = []
                
                for section in guidance_sections:
                    if section.strip():
                        # Format each section
                        lines = section.split('\n')
                        title = lines[0]
                        content = '\n'.join(lines[1:])
                        
                        # Clean up content - remove all bullet points, numbers, and extra whitespace
                        content = content.replace('1. ', '').replace('2. ', '').replace('3. ', '').replace('4. ', '').replace('5. ', '')
                        content = content.replace('* ', '').replace('- ', '')
                        content = content.replace('\n', ' ').strip()  # Convert to single paragraph
                        
                        # Remove any remaining numbers or bullets at start of lines
                        content = '\n'.join(line.lstrip('0123456789.*- ') for line in content.split('\n'))
                        content = content.replace('\n', ' ').strip()  # Convert to single paragraph again
                        
                        # Format as code block with proper spacing
                        formatted_guidance.append(f"*{title}*\n```\n{content}\n```")
                
                blocks.extend([
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Expert Analysis:*\n" + "\n\n".join(formatted_guidance)
                        }
                    },
                    {
                        "type": "divider"
                    }
                ])
        
        return blocks
    
    def start(self):
        """Start the Slack app in socket mode."""
        handler = SocketModeHandler(self.app, os.getenv('SLACK_APP_TOKEN'))
        handler.start()

if __name__ == "__main__":
    security_agent = SecurityAgent()
    handler = SlackHandler(security_agent)
    handler.start() 