from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from typing import Dict, Any, Optional, List
import logging
import os
from dotenv import load_dotenv
from security_agent import SecurityAgent
import asyncio
import traceback
import requests
import time
import json
import re
from slack_sdk.errors import SlackApiError

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
        
        # Set up detailed logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        # Add a file handler to capture detailed logs
        file_handler = logging.FileHandler('slack_handler.log')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Initialize Slack app with token and handler
        self.logger.info("Initializing Slack app")
        self.slack_app_token = os.getenv('SLACK_APP_TOKEN')
        self.slack_signing_secret = os.getenv('SLACK_SIGNING_SECRET')
        self.slack_bot_token = os.getenv('SLACK_BOT_TOKEN')
        
        if not self.slack_app_token or not self.slack_signing_secret or not self.slack_bot_token:
            self.logger.error("Missing required Slack tokens")
            self.logger.error(f"APP_TOKEN: {'Present' if self.slack_app_token else 'Missing'}")
            self.logger.error(f"SIGNING_SECRET: {'Present' if self.slack_signing_secret else 'Missing'}")
            self.logger.error(f"BOT_TOKEN: {'Present' if self.slack_bot_token else 'Missing'}")
            raise ValueError("Missing required Slack tokens")
        
        # Initialize Slack app
        self.app = App(
            token=self.slack_bot_token,
            signing_secret=self.slack_signing_secret
        )
        
        # Initialize WebClient for API calls
        self.client = WebClient(token=self.slack_bot_token)
        
        # Verify Slack token
        try:
            auth_test = self.client.auth_test()
            self.logger.info(f"Slack authentication successful, connected as: {auth_test['user']}")
        except Exception as e:
            self.logger.error(f"Slack authentication failed: {str(e)}")
            raise
        
        # Track recently processed commands to prevent duplicates
        self.processed_commands = {}
        
        # Register event handlers
        self.register_handlers()
        
        # Message retry configuration
        self.max_retries = 3
        self.retry_delay = 1  # seconds
    
    def register_handlers(self):
        """Register all event handlers with the Slack app."""
        # Command handlers
        self.app.command("/security")(self.handle_security_command_wrapper)
        
        # Event handlers
        self.app.event("message")(self.handle_message)
        self.app.event("app_mention")(self.handle_app_mention)
        
        # Action handlers
        self.app.action("incident_status")(self.handle_incident_status)
        self.app.action("knowledge_search")(self.handle_knowledge_search)
        
        logger.info("Successfully registered all handlers")
    
    def handle_security_command_wrapper(self, ack, body, respond):
        """Non-async wrapper for the async security command handler."""
        # First acknowledge the request
        ack()
        
        # Create a function to process the command in the background
        def process_command():
            try:
                # Extract command text
                text = body.get("text", "").strip()
                user_id = body.get("user_id")
                channel_id = body.get("channel_id")
                
                # If no command text provided, show help
                if not text or text.lower() == "help":
                    help_text = self._generate_help_message()
                    respond(text=help_text)
                    return
                
                # Send initial response
                loading_text = f"Processing your request: `{text[:50]}{'...' if len(text) > 50 else ''}`"
                respond(text=loading_text)
                
                # Process the request
                result = self.security_agent.process_command(text)
                
                # Send response based on result format
                if isinstance(result, dict) and "original_results" in result:
                    # Format results for Slack
                    for i, result_item in enumerate(result["original_results"]):
                        # Get title and content
                        title = result_item.get("title", "Untitled")
                        content = result_item.get("content", "")
                        guidance = result_item.get("guidance", "")
                        
                        # Clean up any remaining formatting that Claude might have included
                        # Remove any lines that look like headers (start with # or have : at the end)
                        guidance_lines = guidance.split('\n')
                        cleaned_lines = []
                        for line in guidance_lines:
                            line = line.strip()
                            # Skip empty lines
                            if not line:
                                continue
                            # Skip lines that look like headers
                            if line.startswith('#') or line.startswith('*') or line.endswith(':'):
                                continue
                            # Add the line to our cleaned list
                            cleaned_lines.append(line)
                        
                        # Join lines back into a single paragraph
                        guidance = ' '.join(cleaned_lines)
                        
                        # Create a Slack-friendly formatted message
                        # Title is bold, content is regular text
                        message = f"*{i+1}. {title}*\n{content}"
                        
                        # Add guidance if it exists as a natural paragraph
                        if guidance:
                            message += f"\n\nInvestigation Prompt:\n{guidance}"
                        
                        # Send the combined message
                        respond(text=message)
                elif isinstance(result, dict) and "message" in result:
                    respond(text=result["message"])
                else:
                    respond(text="I couldn't process your request properly.")
                    
            except Exception as e:
                error_message = f"I encountered an error processing your request: {str(e)}"
                logging.error(f"Error processing security command: {e}")
                logging.error(traceback.format_exc())
                respond(text=error_message)
        
        # Run in a separate thread to avoid blocking
        import threading
        thread = threading.Thread(target=process_command)
        thread.daemon = True
        thread.start()
    
    async def handle_message(self, event):
        """Handle message events."""
        try:
            user_id = event['user']
            text = event.get('text', '')
            channel_id = event['channel']
            thread_ts = event.get('thread_ts', None)
            ts = event.get('ts', None)
            
            # Skip messages from the bot itself
            if 'bot_id' in event:
                return
            
            # Only process direct messages or replies to the bot's messages
            is_dm = channel_id.startswith('D')
            is_reply_to_bot = False
            
            if thread_ts:
                try:
                    # Check if this is a reply to a bot message
                    history = self.client.conversations_history(
                        channel=channel_id,
                        latest=thread_ts,
                        inclusive=True,
                        limit=1
                    )
                    if history and history['messages'] and 'bot_id' in history['messages'][0]:
                        is_reply_to_bot = True
                except Exception as e:
                    logger.error(f"Error checking if reply to bot: {e}")
            
            if not (is_dm or is_reply_to_bot):
                return
            
            # Send typing indicator
            self.client.conversations_mark(
                channel=channel_id,
                ts=ts
            )
            
            try:
                self.client.reactions_add(
                    channel=channel_id,
                    timestamp=thread_ts or ts,
                    name="eyes"
                )
            except Exception as e:
                logger.warning(f"Could not add reaction: {e}")
            
            threading_ts = thread_ts or ts
            
            try:
                # Process the message
                response_blocks = await self.security_agent.process_message(
                    text=text,
                    user_id=user_id,
                    channel_id=channel_id
                )
                
                # Send the response
                if response_blocks:
                    if isinstance(response_blocks, str):
                        self._send_message_with_retry(lambda text=response_blocks: self.client.chat_postMessage(
                            channel=channel_id,
                            thread_ts=threading_ts,
                            text=text
                        ), response_blocks)
                    else:
                        self._send_blocks_with_retry(lambda blocks=response_blocks: self.client.chat_postMessage(
                            channel=channel_id,
                            thread_ts=threading_ts,
                            blocks=blocks
                        ), response_blocks)
                else:
                    default_response = "I'm sorry, I couldn't process your request. Please try again or contact support."
                    self._send_message_with_retry(lambda text=default_response: self.client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=threading_ts,
                        text=text
                    ), default_response)
                
                # Remove the eyes reaction
                try:
                    self.client.reactions_remove(
                        channel=channel_id,
                        timestamp=thread_ts or ts,
                        name="eyes"
                    )
                except Exception as e:
                    logger.warning(f"Could not remove reaction: {e}")
                
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                logger.error(traceback.format_exc())
                
                error_message = f"I encountered an error processing your request: {str(e)}"
                self._send_message_with_retry(lambda text=error_message: self.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=threading_ts,
                    text=text
                ), error_message)
                
                # Remove the eyes reaction
                try:
                    self.client.reactions_remove(
                        channel=channel_id,
                        timestamp=thread_ts or ts,
                        name="eyes"
                    )
                except Exception as e:
                    logger.warning(f"Could not remove reaction: {e}")
                
        except Exception as e:
            logger.error(f"Error handling message event: {e}")
            logger.error(traceback.format_exc())
    
    async def handle_app_mention(self, event, say):
        """Handle app mentions (@security) in channels."""
        try:
            # Extract user query - remove the app mention
            text = event.get("text", "")
            user_id = event.get("user")
            channel_id = event.get("channel")
            
            # Remove the app mention from the text
            app_mention_pattern = r"<@[A-Z0-9]+>"
            clean_text = re.sub(app_mention_pattern, "", text).strip()
            
            # If no actual query, send help
            if not clean_text:
                help_text = self._generate_help_message()
                self._send_message_with_retry(
                    lambda: say(text=help_text),
                    help_text
                )
                return
                
            # Send a loading message
            loading_message = f"I'm processing your request: `{clean_text[:50]}{'...' if len(clean_text) > 50 else ''}`"
            loading_response = self._send_message_with_retry(
                lambda: say(text=loading_message),
                loading_message
            )
            
            if not loading_response:
                # If we couldn't send a loading message, still try to process the request
                loading_ts = None
            else:
                loading_ts = loading_response.get("ts")
            
            # Process the query
            try:
                agent_response = await self.security_agent.process_message(clean_text, user_id, channel_id)
                
                # Delete loading message if possible
                if loading_ts:
                    try:
                        self.client.chat_delete(channel=channel_id, ts=loading_ts)
                    except Exception as e:
                        logging.error(f"Failed to delete loading message: {e}")
                
                # Format and send the response
                if isinstance(agent_response, dict) and agent_response.get("blocks"):
                    self._send_blocks_with_retry(
                        lambda: say(blocks=agent_response["blocks"]),
                        agent_response["blocks"]
                    )
                else:
                    response_text = agent_response if isinstance(agent_response, str) else "I couldn't process your request properly."
                    self._send_message_with_retry(
                        lambda: say(text=response_text),
                        response_text
                    )
                    
            except Exception as process_error:
                # Delete loading message if possible
                if loading_ts:
                    try:
                        self.client.chat_delete(channel=channel_id, ts=loading_ts)
                    except Exception as e:
                        logging.error(f"Failed to delete loading message: {e}")
                
                error_msg = f"Sorry, I encountered an error while processing your request: {str(process_error)}"
                logging.error(f"Error processing message: {process_error}")
                logging.error(traceback.format_exc())
                
                self._send_message_with_retry(
                    lambda: say(text=error_msg),
                    error_msg
                )
                
        except Exception as e:
            logging.error(f"Error in handle_app_mention: {e}")
            logging.error(traceback.format_exc())
            try:
                self._send_message_with_retry(
                    lambda: say(text=f"Sorry, I encountered an error: {str(e)}"),
                    f"Sorry, I encountered an error: {str(e)}"
                )
            except Exception as msg_error:
                logging.error(f"Failed to send error message: {msg_error}")
    
    async def handle_incident_status(self, channel_id, thread_ts, text):
        """Handle incident status requests."""
        try:
            # Send loading message
            loading_message = "Checking incident status..."
            loading_response = await self.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=loading_message
            )
            loading_ts = loading_response['ts']
            
            # Extract any specific incident numbers mentioned
            incident_match = re.search(r"(?:incident|inc)[:\s#]+(\d+)", text, re.IGNORECASE)
            incident_id = incident_match.group(1) if incident_match else None
            
            if incident_id:
                # Get specific incident status
                status_blocks = await self.security_agent.get_incident_status(incident_id)
                
                # Delete loading message
                try:
                    await self.client.chat_delete(
                        channel=channel_id,
                        ts=loading_ts
                    )
                except Exception as e:
                    logging.warning(f"Failed to delete loading message: {e}")
                
                # Send status with retry
                if isinstance(status_blocks, str):
                    self._send_message_with_retry(lambda text=status_blocks: self.client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=text
                    ), status_blocks)
                else:
                    self._send_blocks_with_retry(lambda blocks=status_blocks: self.client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        blocks=blocks
                    ), status_blocks)
            else:
                # Get recent incidents summary
                status_blocks = await self.security_agent.get_recent_incidents()
                
                # Delete loading message
                try:
                    await self.client.chat_delete(
                        channel=channel_id,
                        ts=loading_ts
                    )
                except Exception as e:
                    logging.warning(f"Failed to delete loading message: {e}")
                
                # Send status with retry
                if isinstance(status_blocks, str):
                    self._send_message_with_retry(lambda text=status_blocks: self.client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=text
                    ), status_blocks)
                else:
                    self._send_blocks_with_retry(lambda blocks=status_blocks: self.client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        blocks=blocks
                    ), status_blocks)
                
        except Exception as e:
            logging.error(f"Error handling incident status: {e}")
            logging.error(traceback.format_exc())
            
            error_message = "I encountered an error checking incident status. Please try again later."
            self._send_message_with_retry(lambda text=error_message: self.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=text
            ), error_message)
    
    async def handle_knowledge_search(self, channel_id, thread_ts, query):
        """Handle knowledge search requests."""
        try:
            # Send loading message
            loading_message = f"Searching for: {query}..."
            loading_response = await self.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=loading_message
            )
            loading_ts = loading_response['ts']
            
            # Perform the search
            search_results = await self.security_agent.search_knowledge_base(query)
            
            # Delete loading message
            try:
                await self.client.chat_delete(
                    channel=channel_id,
                    ts=loading_ts
                )
            except Exception as e:
                logging.warning(f"Failed to delete loading message: {e}")
            
            # Format the results
            if search_results and len(search_results) > 0:
                blocks = self._format_search_results_to_blocks(query, search_results)
                
                # Send results with retry
                self._send_blocks_with_retry(lambda blocks=blocks: self.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    blocks=blocks
                ), blocks)
            else:
                no_results_message = f"No results found for '{query}'. Please try a different search term."
                self._send_message_with_retry(lambda text=no_results_message: self.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=text
                ), no_results_message)
                
        except Exception as e:
            logging.error(f"Error handling knowledge search: {e}")
            logging.error(traceback.format_exc())
            
            error_message = f"I encountered an error searching for '{query}'. Please try again later."
            self._send_message_with_retry(lambda text=error_message: self.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=text
            ), error_message)
    
    def start(self):
        """Start the Slack app in socket mode."""
        try:
            logger.info("Starting Slack app in Socket Mode")
            handler = SocketModeHandler(self.app, self.slack_app_token)
            handler.start()
        except Exception as e:
            logger.error(f"Error starting Slack app: {str(e)}")
            raise

    def _send_message_with_retry(self, message_func, text, max_retries=3, retry_delay=2):
        """Send a message with retry logic."""
        retries = 0
        while retries < max_retries:
            try:
                return message_func()
            except Exception as e:
                retries += 1
                logging.error(f"Error sending message (attempt {retries}/{max_retries}): {e}")
                if retries >= max_retries:
                    logging.error(f"Failed to send message after {max_retries} attempts")
                    logging.error(f"Message content: {text[:100]}...")
                    break
                time.sleep(retry_delay)
        return None

    def _send_blocks_with_retry(self, func, blocks):
        """Send blocks with retry."""
        retries = 0
        max_retries = 3
        retry_delay = 2
        
        while retries < max_retries:
            try:
                return func()
            except Exception as e:
                retries += 1
                logger.error(f"Error sending blocks (attempt {retries}/{max_retries}): {e}")
                if retries >= max_retries:
                    logger.error(f"Failed to send blocks after {max_retries} attempts")
                    break
                time.sleep(retry_delay)
        return None

    def _generate_help_message(self):
        """Generate help message for the Security Agent."""
        return ("*Security Agent Help*\n\n"
                "*Available Commands:*\n"
                "• `/security help` - Show this help message\n"
                "• `/security status` - Check current incident status\n"
                "• `/security search [query]` - Search security knowledge base\n"
                "• Direct message me or mention me in a channel")

if __name__ == "__main__":
    security_agent = SecurityAgent()
    handler = SlackHandler(security_agent)
    handler.start() 