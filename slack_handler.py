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
import aiohttp
from datetime import datetime

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
        self.app.action("ask_charlotte")(self.handle_ask_charlotte)
        
        # View submission handlers
        self.app.view("charlotte_modal")(self.handle_charlotte_submission)
        
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
                    # Check if we should use block formatting with buttons
                    if result.get("use_blocks", False):
                        # Format results using blocks to include the Ask Charlotte button
                        formatted_blocks = self.security_agent._format_slack_blocks(result["original_results"])
                        
                        # Send blocks using the respond function, not direct API call
                        respond(
                            blocks=formatted_blocks,
                            text=f"Found {len(result['original_results'])} relevant security knowledge articles"
                        )
                    else:
                        # Use the existing text-based formatting
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
    
    async def handle_ask_charlotte(self, ack, body, client):
        """Handle the Ask Charlotte button click to generate step-by-step investigation steps."""
        try:
            # Acknowledge the request immediately
            await ack()
            
            # Log the entire body for debugging
            logger.debug(f"Ask Charlotte button clicked with body: {json.dumps(body)[:1000]}...")
            
            # Extract data
            channel_id = body["channel"]["id"]
            thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
            user_id = body["user"]["id"]
            
            # Parse the value from the button
            try:
                value_data = json.loads(body["actions"][0]["value"])
                title = value_data.get("title", "Security Investigation")
                guidance = value_data.get("guidance", "")
                article_id = value_data.get("article_id", "unknown")
                logger.info(f"Parsed button value: title='{title[:30]}...', article_id='{article_id}', guidance length={len(guidance)}")
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Error parsing button value: {e}")
                title = "Security Investigation"
                guidance = ""
                article_id = "unknown"
            
            # Open a modal dialog for the user to edit/confirm the prompt
            try:
                logger.info(f"Opening modal dialog for user {user_id} in channel {channel_id}")
                result = await client.views_open(
                    trigger_id=body["trigger_id"],
                    view={
                        "type": "modal",
                        "callback_id": "charlotte_modal",
                        "title": {
                            "type": "plain_text",
                            "text": "Ask Charlotte"
                        },
                        "submit": {
                            "type": "plain_text",
                            "text": "Submit"
                        },
                        "close": {
                            "type": "plain_text",
                            "text": "Cancel"
                        },
                        "private_metadata": json.dumps({
                            "channel_id": channel_id,
                            "thread_ts": thread_ts,
                            "article_id": article_id
                        }),
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"*Please edit or confirm your request to Charlotte about:*\n{title}"
                                }
                            },
                            {
                                "type": "input",
                                "block_id": "prompt_block",
                                "element": {
                                    "type": "plain_text_input",
                                    "multiline": True,
                                    "action_id": "prompt_input",
                                    "initial_value": guidance,
                                    "placeholder": {
                                        "type": "plain_text",
                                        "text": "Edit your request to Charlotte..."
                                    }
                                },
                                "label": {
                                    "type": "plain_text",
                                    "text": "Security Guidance Request"
                                }
                            }
                        ]
                    }
                )
                logger.debug(f"Successfully opened modal: {result}")
            except Exception as modal_error:
                logger.error(f"Error opening modal: {modal_error}")
                logger.error(traceback.format_exc())
                error_message = "I had trouble opening the dialog. Please try again later."
                await client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=error_message
                )
        
        except Exception as e:
            logger.error(f"Error handling Ask Charlotte button: {e}")
            logger.error(traceback.format_exc())
            try:
                await client.chat_postMessage(
                    channel=body["channel"]["id"],
                    thread_ts=body.get("message", {}).get("thread_ts"),
                    text=f"I encountered an error processing your request: {str(e)}"
                )
            except Exception as msg_error:
                logger.error(f"Failed to send error message: {msg_error}")
    
    # Add view submission handler for the modal
    async def handle_charlotte_submission(self, ack, body, client):
        """Handle the submission of the Charlotte modal dialog."""
        try:
            # Acknowledge the request immediately
            await ack()
            
            # Log the submission for debugging
            logger.debug(f"Charlotte modal submitted with body: {json.dumps(body)[:1000]}...")
            
            # Extract data from the submission
            view = body["view"]
            private_metadata = json.loads(view["private_metadata"])
            channel_id = private_metadata["channel_id"]
            thread_ts = private_metadata["thread_ts"]
            article_id = private_metadata["article_id"]
            
            logger.info(f"Processing Charlotte modal submission for article_id: {article_id} in channel: {channel_id}")
            
            # Get the user's edited prompt
            user_prompt = view["state"]["values"]["prompt_block"]["prompt_input"]["value"]
            logger.info(f"User prompt length: {len(user_prompt)} characters")
            
            # Send a loading message
            loading_message = "Processing your request with Charlotte..."
            loading_response = await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=loading_message
            )
            loading_ts = loading_response["ts"]
            
            # Process the request with Charlotte (Heroku Inference)
            try:
                logger.info("Starting Charlotte request processing")
                
                # 1. Process with Heroku Inference for the 10-step analysis
                analysis_result = await self._process_charlotte_request(user_prompt, article_id)
                logger.info(f"Received Charlotte analysis result with {len(analysis_result)} characters")
                
                # 2. Send to Salesforce AgentForce via Heroku AppLink
                logger.info("Triggering Salesforce flow")
                salesforce_result = await self._trigger_salesforce_flow(user_prompt, article_id, channel_id, thread_ts)
                logger.info(f"Salesforce flow result: {salesforce_result}")
                
                # Delete loading message
                try:
                    await client.chat_delete(
                        channel=channel_id,
                        ts=loading_ts
                    )
                except Exception as e:
                    logger.warning(f"Failed to delete loading message: {e}")
                
                # Format and send the response
                logger.info("Formatting Charlotte response")
                blocks = self._format_charlotte_response(analysis_result)
                
                logger.info(f"Sending formatted response with {len(blocks)} blocks")
                response = await client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    blocks=blocks
                )
                logger.info(f"Response successfully sent: {response.get('ts')}")
                
            except Exception as process_error:
                logger.error(f"Error processing with Charlotte: {process_error}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                
                # Delete loading message
                try:
                    await client.chat_delete(
                        channel=channel_id,
                        ts=loading_ts
                    )
                except Exception as e:
                    logger.warning(f"Failed to delete loading message: {e}")
                
                error_message = f"I encountered an error processing your request with Charlotte: {str(process_error)}"
                await client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=error_message
                )
                
        except Exception as e:
            logger.error(f"Error handling Charlotte modal submission: {e}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
    
    async def _process_charlotte_request(self, prompt, article_id):
        """Process the request with Charlotte via Heroku Inference."""
        try:
            # Get additional context about the article if possible
            article_context = await self._get_article_context(article_id)
            
            # Construct the messages for the Charlotte API with enhanced context
            system_message = """You are Charlotte, a security operations assistant that provides structured, step-by-step guidance for security investigations. 
Your task is to analyze security guidance and convert it into a detailed, actionable 10-step process for security analysts.
Each step should be concrete, clear, and specific to the security issue at hand."""
            
            user_message = f"""Based on the following security guidance prompt, provide a detailed 10-step process for investigating and addressing this security issue.

CONTEXT:
{article_context}

SECURITY GUIDANCE:
{prompt}

FORMAT REQUIREMENTS:
1. Provide exactly 10 numbered steps
2. Each step should begin with an action verb
3. Include specific tools, commands, or resources where applicable
4. Keep each step concise but detailed enough to be actionable
5. Format as a clean numbered list (1-10)
"""
            
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ]
            
            # Call the Heroku Inference API via the inference client
            logger.info(f"Sending enhanced request to inference service with {len(user_message)} characters")
            result = self.security_agent.inference_client.chat_completion(messages)
            
            return result
        except Exception as e:
            logger.error(f"Error processing Charlotte request: {e}")
            raise
    
    async def _get_article_context(self, article_id):
        """Retrieve additional context about the security article."""
        try:
            # Check if article_id is in a valid format
            if not article_id or article_id == "unknown":
                return "No additional context available for this security issue."
            
            # Try to get the article from the database
            try:
                # Use the non-async database call
                article = self.security_agent.db_manager.get_knowledge_by_id(article_id)
                if article:
                    return f"Article Title: {article.title}\nCategory: {article.category if hasattr(article, 'category') else 'General'}\nContent: {article.content[:500]}..."
            except Exception as db_error:
                logger.warning(f"Could not retrieve article context from database: {str(db_error)}")
            
            # If we get here, we couldn't get article info from the database
            return "Limited context available for this security issue."
        except Exception as e:
            logger.warning(f"Error getting article context: {str(e)}")
            return "No additional context available."
    
    async def _trigger_salesforce_flow(self, prompt, article_id, channel_id, thread_ts):
        """Trigger Salesforce flow via Heroku AppLink."""
        try:
            # Construct the payload for the Salesforce AgentForce flow
            salesforce_payload = {
                "incident_data": {
                    "source": "Security Agent",
                    "type": "Investigation",
                    "details": {
                        "article_id": article_id,
                        "prompt": prompt,
                        "channel_id": channel_id,
                        "thread_ts": thread_ts,
                        "timestamp": datetime.now().isoformat()
                    }
                },
                "query_text": prompt
            }
            
            # Get Heroku AppLink URL from environment
            applink_url = os.getenv("HEROKU_APPLINK_URL")
            if not applink_url:
                logger.warning("Heroku AppLink URL not configured, skipping Salesforce integration")
                return
            
            # Send the request to Heroku AppLink
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{applink_url}/api/agentforce/security-triage",
                    json=salesforce_payload,
                    headers={
                        "Authorization": f"Bearer {os.getenv('HEROKU_APPLINK_TOKEN')}",
                        "Content-Type": "application/json"
                    }
                ) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        logger.error(f"Error from AppLink: {response.status} - {response_text}")
                        raise Exception(f"AppLink returned status {response.status}")
                    
                    result = await response.json()
                    logger.info(f"Successfully triggered Salesforce flow: {result.get('status')}")
                    return result
        except Exception as e:
            logger.error(f"Error triggering Salesforce flow: {e}")
            logger.error(traceback.format_exc())
            # We'll log the error but not raise it to ensure the Charlotte response still gets sent
            return {"status": "error", "message": str(e)}
    
    def _format_charlotte_response(self, response):
        """Format the Charlotte response into Slack blocks."""
        blocks = []
        
        # Add header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Charlotte's Security Investigation Steps",
                "emoji": True
            }
        })
        
        # Add divider
        blocks.append({"type": "divider"})
        
        # Process the response text
        # Check if response is formatted with numbers already
        steps_pattern = re.compile(r"(\d+)[.)\]]\s+(.*?)(?=(?:\n\d+[.)\]]\s+)|$)", re.DOTALL)
        matches = steps_pattern.findall(response)
        
        if matches:
            # Response is already formatted with numbers
            for step_num, step_content in matches:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Step {step_num}:* {step_content.strip()}"
                    }
                })
        else:
            # Split by newlines and try to create steps
            lines = response.split('\n')
            step_num = 1
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Check if line starts with a number already
                if re.match(r"^\d+[.)]", line):
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{line}"
                        }
                    })
                else:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Step {step_num}:* {line}"
                        }
                    })
                    step_num += 1
        
        # Add note that Salesforce flow has been triggered
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_A Salesforce AgentForce workflow has been triggered for this investigation._"
                }
            ]
        })
        
        return blocks
    
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