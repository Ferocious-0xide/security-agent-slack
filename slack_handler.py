import logging
import os
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Dict, Any, Optional
from security_agent import SecurityAgent
import asyncio
import traceback
import sys
import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

class SlackHandler:
    def __init__(self):
        try:
            logger.debug("Starting SlackHandler initialization...")
            load_dotenv()
            logger.debug("Environment variables loaded")
            
            # Validate required environment variables
            required_vars = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET"]
            missing_vars = [var for var in required_vars if not os.getenv(var)]
            if missing_vars:
                raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
            
            logger.debug("Initializing Slack app...")
            self.app = App(
                token=os.getenv("SLACK_BOT_TOKEN"),
                signing_secret=os.getenv("SLACK_SIGNING_SECRET")
            )
            
            # Initialize WebClient for API calls
            self.client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
            
            # Verify app configuration
            try:
                auth_test = self.client.auth_test()
                logger.debug(f"App authenticated successfully. Bot user ID: {auth_test['user_id']}")
                logger.debug(f"Team: {auth_test['team']}")
                logger.debug(f"App name: {auth_test.get('app_name', 'N/A')}")
                logger.debug(f"Enterprise ID: {auth_test.get('enterprise_id', 'N/A')}")
            except SlackApiError as e:
                logger.error(f"Failed to authenticate app: {str(e)}")
                raise
            
            logger.debug("Slack app initialized")
            
            logger.debug("Initializing security agent...")
            self.security_agent = SecurityAgent()
            logger.debug("Security agent initialized")
            
            logger.debug("Setting up handlers...")
            self.setup_handlers()
            logger.debug("Handlers setup completed")
            
            logger.info("SlackHandler initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing SlackHandler: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def setup_handlers(self):
        """Setup Slack command and event handlers."""
        try:
            logger.debug("Setting up command handlers...")
            
            # Command handlers
            def handle_security_command(ack, command, say):
                logger.debug("=== Security command handler called ===")
                logger.debug(f"Command payload: {command}")
                
                # Acknowledge the command immediately
                ack()
                
                try:
                    # Extract the response_url from the command payload
                    response_url = command.get('response_url')
                    logger.debug(f"Response URL: {response_url}")
                    
                    # Run async operation in event loop
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        response = loop.run_until_complete(
                            self.security_agent.process_slack_command(
                                command['command'],
                                command['text']
                            )
                        )
                        logger.debug(f"Security agent response: {response}")
                    finally:
                        loop.close()
                    
                    # Helper function to send messages
                    async def send_message(message, blocks=None):
                        try:
                            if response_url:
                                logger.debug("Using response_url to send message")
                                async with aiohttp.ClientSession() as session:
                                    async with session.post(
                                        response_url,
                                        json={
                                            "text": message,
                                            "blocks": blocks
                                        }
                                    ) as resp:
                                        logger.debug(f"Response URL status: {resp.status}")
                                        if resp.status != 200:
                                            logger.error(f"Failed to send message via response_url: {resp.status}")
                                            # Fallback to say()
                                            say(message, blocks=blocks)
                            else:
                                logger.debug("Using say() to send message")
                                say(message, blocks=blocks)
                        except Exception as e:
                            logger.error(f"Error sending message: {str(e)}")
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            # Try fallback
                            try:
                                say(message, blocks=blocks)
                            except Exception as say_error:
                                logger.error(f"Failed to send message via say(): {str(say_error)}")
                    
                    # Handle the response
                    if "error" in response:
                        logger.error(f"Error in response: {response['error']}")
                        asyncio.run(send_message(f"Error: {response['error']}"))
                    elif "results" in response:
                        logger.debug(f"Processing {len(response['results'])} results")
                        blocks = []
                        for result in response['results']:
                            logger.debug(f"Adding result block: {result['title']}")
                            blocks.append({
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"*{result['title']}*\n{result['content']}\n\n*Claude.ai Prompt:*\n```{result['claude_prompt']}```"
                                }
                            })
                        asyncio.run(send_message("Search Results:", blocks=blocks))
                    else:
                        logger.error(f"Unexpected response format: {response}")
                        asyncio.run(send_message("Error: Unexpected response format"))
                
                except Exception as e:
                    logger.error(f"Error in security command handler: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    try:
                        say(f"Error processing command: {str(e)}")
                    except Exception as say_error:
                        logger.error(f"Failed to send error message: {str(say_error)}")
            
            # Register the command handler
            self.app.command("/security")(handle_security_command)
            logger.debug("Registered /security command handler")
            
            # Event handlers
            logger.debug("Setting up event handlers...")
            self.app.event("message")(self.handle_message)
            self.app.event("app_mention")(self.handle_app_mention)
            logger.debug("Registered event handlers")
            
            # Action handlers
            logger.debug("Setting up action handlers...")
            self.app.action("incident_status")(self.handle_incident_status)
            self.app.action("knowledge_search")(self.handle_knowledge_search)
            logger.debug("Registered action handlers")
            
            logger.debug("All handlers setup completed")
        except Exception as e:
            logger.error(f"Error setting up handlers: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def _send_message(self, channel_id: str, message: str):
        """Send a message to a channel with error handling."""
        try:
            self.client.chat_postMessage(
                channel=channel_id,
                text=message
            )
        except SlackApiError as e:
            if e.response["error"] == "not_in_channel":
                # Try to join the channel
                try:
                    self.client.conversations_join(channel=channel_id)
                    # Retry sending the message
                    self.client.chat_postMessage(
                        channel=channel_id,
                        text=message
                    )
                except SlackApiError as join_error:
                    logger.error("Bot cannot join the channel. Please invite the bot to the channel.")
                    # Send a direct message to the user who triggered the command
                    self._send_dm_to_user(
                        user_id=self._get_user_id_from_channel(channel_id),
                        message="I need to be invited to the channel to respond. Please use `/invite @SecurityBot` in the channel."
                    )
                    raise
            elif e.response["error"] == "channel_not_found":
                logger.error("Channel not found. Please check the channel ID.")
                raise
            else:
                logger.error(f"Error sending message: {str(e)}")
                raise
    
    def _get_user_id_from_channel(self, channel_id: str) -> str:
        """Get the user ID from the channel context."""
        try:
            # Get channel info to find the user who triggered the command
            channel_info = self.client.conversations_info(channel=channel_id)
            return channel_info["channel"]["creator"]
        except SlackApiError:
            # If we can't get the channel info, return a default user ID
            return self.client.auth_test()["user_id"]
    
    def _send_dm_to_user(self, user_id: str, message: str):
        """Send a direct message to a user."""
        try:
            # Open a DM channel with the user
            dm_channel = self.client.conversations_open(users=user_id)
            # Send the message
            self.client.chat_postMessage(
                channel=dm_channel["channel"]["id"],
                text=message
            )
        except SlackApiError as e:
            logger.error(f"Error sending DM: {str(e)}")
            raise
    
    def _send_error_message(self, channel_id: str, error_message: str):
        """Send an error message to a channel."""
        try:
            self.client.chat_postMessage(
                channel=channel_id,
                text=f"❌ Error: {error_message}"
            )
        except SlackApiError as e:
            logger.error(f"Error sending error message: {str(e)}")
            raise
    
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
        try:
            logger.debug("Starting Slack app in socket mode...")
            app_token = os.getenv("SLACK_APP_TOKEN")
            if not app_token:
                raise ValueError("SLACK_APP_TOKEN environment variable is not set")
            
            logger.debug("Creating socket mode handler...")
            handler = SocketModeHandler(self.app, app_token)
            logger.debug("Socket mode handler created")
            
            logger.info("Starting app...")
            handler.start()
            logger.info("App started successfully")
        except Exception as e:
            logger.error(f"Error starting Slack app: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

if __name__ == "__main__":
    try:
        logger.info("Starting Security Agent Slack integration...")
        handler = SlackHandler()
        logger.info("SlackHandler instance created, starting app...")
        handler.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1) 