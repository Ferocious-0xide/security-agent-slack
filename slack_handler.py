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
        
        self.logger.info("SlackHandler initialized with custom Charlotte button handlers")
        
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
        
        # Register the Ask Charlotte button handler using a direct handler
        def ask_charlotte_handler(ack, body, client):
            ack()
            logger.info(f"Ask Charlotte button clicked in channel: {body.get('channel', {}).get('id')}")
            logger.debug(f"Button body: {json.dumps(body)[:500]}...")
            
            # Extract necessary data for direct processing
            channel_id = body.get("channel", {}).get("id")
            if not channel_id:
                logger.error("No channel ID in button payload")
                return
            
            # Get the message timestamp - this is the timestamp of the message containing the button
            message_ts = body.get("message", {}).get("ts")
            # Get thread_ts if the message is already in a thread
            thread_ts = body.get("message", {}).get("thread_ts")
            
            # For improved clarity, log the timestamps
            logger.info(f"Button clicked in message with ts: {message_ts}, thread_ts: {thread_ts}")
            
            response_url = body.get("response_url")
            
            # Parse the button value
            try:
                value_data = json.loads(body["actions"][0]["value"])
                title = value_data.get("title", "Security Investigation")
                guidance = value_data.get("guidance", "")
                article_id = value_data.get("article_id", "unknown")
                is_original_message = value_data.get("original_message", False)
                initial_command = value_data.get("initial_command", "")  # Get the initial command if available
                
                # Store additional metadata about the original command
                metadata = {
                    "channel_id": channel_id,
                    "message_ts": message_ts,  # Store message_ts for use in replies
                    "thread_ts": thread_ts,    # Store thread_ts if it exists
                    "article_id": article_id,
                    "response_url": response_url,
                    "is_original_message": is_original_message,
                    "initial_command": initial_command  # Include the initial command in metadata
                }
                
                logger.info(f"Opening modal with metadata: {json.dumps(metadata)[:200]}...")
                
                # Open the modal directly
                client.views_open(
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
                        "private_metadata": json.dumps(metadata),
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
            except Exception as e:
                logger.error(f"Error in ask_charlotte_handler: {e}")
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"I encountered an error opening the dialog: {str(e)}"
                )
        
        self.app.action("ask_charlotte")(ask_charlotte_handler)
        
        # Register the modal submission handler with direct processing
        def charlotte_modal_handler(ack, body, client, view):
            # Acknowledge the submission
            ack()
            logger.info(f"Charlotte modal submitted with view_id: {view.get('id')}")
            
            try:
                # Extract data from the submission
                private_metadata = json.loads(body["view"]["private_metadata"])
                logger.info(f"Extracted private_metadata: {private_metadata}")
                
                channel_id = private_metadata.get("channel_id")
                message_ts = private_metadata.get("message_ts")  # TS of the message containing the button
                thread_ts = private_metadata.get("thread_ts")     # Thread TS if already in a thread
                article_id = private_metadata.get("article_id")
                response_url = private_metadata.get("response_url")
                is_original_message = private_metadata.get("is_original_message", False)
                initial_command = private_metadata.get("initial_command", "")
                
                # MODIFY: Never set reply_ts regardless of is_original_message
                # Always post as a new message instead of a thread reply
                reply_ts = None
                
                user_id = body.get("user", {}).get("id")
                
                logger.info(f"Processing request - channel: {channel_id}, message_ts: {message_ts}, thread_ts: {thread_ts}, reply_ts: {reply_ts}")
                
                if not channel_id or not user_id:
                    logger.error("Missing channel_id or user_id in modal submission")
                    return
                    
                # Get the user's edited prompt
                user_prompt = body["view"]["state"]["values"]["prompt_block"]["prompt_input"]["value"]
                logger.info(f"User prompt: {user_prompt[:50]}... ({len(user_prompt)} chars)")
                
                # Call the inference API directly
                messages = [
                    {"role": "system", "content": "You are Charlotte, a security operations assistant that provides structured, step-by-step guidance for security investigations."},
                    {"role": "user", "content": f"Based on the following security guidance prompt, provide a detailed 10-step process for investigating and addressing this security issue. Format the response as a numbered list with clear, actionable steps.\n\nPrompt: {user_prompt}"}
                ]
                
                # Process with Heroku Inference
                result = self.security_agent.inference_client.chat_completion(messages)
                logger.info(f"Received response from inference API: {len(result)} chars")
                
                # Store the user prompt and response in the database
                try:
                    # Extract article_id without the "article_" prefix
                    numeric_article_id = None
                    if article_id and article_id.startswith("article_"):
                        try:
                            numeric_article_id = int(article_id.replace("article_", ""))
                        except ValueError:
                            logger.warning(f"Could not parse article_id: {article_id}")
                    
                    # Store in database
                    stored_prompt = self.security_agent.db_manager.store_user_prompt(
                        user_id=user_id,
                        channel_id=channel_id,
                        prompt_text=user_prompt,
                        response_text=result,
                        article_id=numeric_article_id
                    )
                    logger.info(f"Stored user prompt in database with ID: {stored_prompt.id}")
                except Exception as db_error:
                    logger.error(f"Error storing user prompt in database: {db_error}")
                    # Continue processing even if database storage fails
                
                # Format the response
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
                
                # Add the user prompt as context
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Investigation Request:*\n{user_prompt[:1000]}{'...' if len(user_prompt) > 1000 else ''}"
                    }
                })
                
                blocks.append({"type": "divider"})
                
                # Add formatted steps, either parsing numbered list format or just as paragraphs
                # Try to parse numbered steps first
                steps = []
                number_pattern = re.compile(r'^\s*(\d+)[\.:\)]?\s+(.+)$', re.MULTILINE)
                matches = number_pattern.findall(result)
                
                if matches:
                    # We have a numbered list
                    for num, content in matches:
                        line = f"*{num}.* {content.strip()}"
                        # Ensure steps aren't too long for Slack
                        if len(line) > 2900:  # Slack has a max size per block
                            line = line[:2900] + "..."
                        steps.append(line)
                
                # If no steps were found, just split by newlines
                if not steps:
                    steps = [line for line in result.split("\n") if line.strip()]
                    # Ensure each step is within Slack's text limits
                    steps = [s[:2900] + "..." if len(s) > 2900 else s for s in steps]
                
                # Add each step as a block
                for step in steps:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": step
                        }
                    })
                
                # Verify blocks don't exceed Slack's limit (50 blocks per message)
                if len(blocks) > 45:  # Leave room for headers and buttons
                    logger.warning(f"Too many blocks ({len(blocks)}), truncating to 45")
                    blocks = blocks[:45]
                    # Add a note about truncation
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "_Note: Some steps were truncated due to message size limits._"
                        }
                    })
                
                # Add note about Salesforce
                blocks.append({"type": "divider"})
                blocks.append({
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_Security investigation steps generated for <@{user_id}> • AgentForce workflow triggered_"
                        }
                    ]
                })
                
                # Add action buttons for Salesforce case creation
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Create Security Case",
                                "emoji": True
                            },
                            "value": json.dumps({
                                "initial_command": initial_command,
                                "user_prompt": user_prompt[:250] if user_prompt else "",  # Truncate user_prompt
                                "steps": result[:250] if result else "",  # Truncate steps to avoid exceeding button value limit
                                "article_id": article_id,
                                "channel_id": channel_id,
                                "message_ts": message_ts,
                                "thread_ts": thread_ts,
                                "reply_ts": reply_ts
                            }),
                            "style": "primary",
                            "action_id": "create_salesforce_case"
                        }
                    ]
                })
                
                # Create a message payload that includes response_type: in_channel
                message_payload = {
                    "blocks": blocks,
                    "text": "Charlotte's Security Investigation Steps"
                }
                
                try:
                    # First, try to join the channel before posting
                    try:
                        logger.info(f"Attempting to join channel {channel_id} before posting")
                        join_result = client.conversations_join(channel=channel_id)
                        logger.info(f"Join channel result: {join_result.get('ok', False)}")
                    except Exception as join_error:
                        logger.warning(f"Could not join channel (this is expected for private channels): {join_error}")
                    
                    # Now try to post the message
                    logger.info(f"Posting public record to channel {channel_id}")
                    
                    # Always post as a new message, never as a thread reply
                    logger.info(f"Posting as a new message")
                    public_message = client.chat_postMessage(
                        channel=channel_id,
                        blocks=blocks,
                        text="Charlotte's Security Investigation Steps"
                    )
                    logger.info(f"Successfully posted new message with ts: {public_message.get('ts')}")
                except Exception as api_error:
                    error_message = str(api_error)
                    logger.error(f"Failed to post response: {error_message}")
                    
                    # If the error is "not_in_channel", attempt to invite the bot to the channel
                    if "not_in_channel" in error_message:
                        try:
                            logger.info(f"Bot not in channel, attempting to notify the user")
                            
                            # EMERGENCY FALLBACK: Use the response_url from the original button click
                            # This URL is still valid for 30 minutes after the button was clicked
                            if response_url:
                                logger.info(f"Using response_url fallback: {response_url[:30]}...")
                                
                                # Create a simplified response
                                simplified_response = {
                                    "response_type": "ephemeral",
                                    "text": "Here's your Charlotte analysis (simplified version due to channel access):",
                                    "blocks": [
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"*Investigation Request:*\n{user_prompt[:300]}{'...' if len(user_prompt) > 300 else ''}"
                                            }
                                        },
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"*Analysis Results:*\n{result[:1500]}{'...' if len(result) > 1500 else ''}"
                                            }
                                        },
                                        {
                                            "type": "context",
                                            "elements": [
                                                {
                                                    "type": "mrkdwn",
                                                    "text": "⚠️ *I couldn't post this to the channel.* To fix this, invite me using `/invite @security_agent` and try again."
                                                }
                                            ]
                                        }
                                    ]
                                }
                                
                                # Send via response_url
                                try:
                                    response = requests.post(
                                        response_url,
                                        json=simplified_response,
                                        headers={"Content-Type": "application/json"},
                                        timeout=5
                                    )
                                    logger.info(f"Response URL fallback status: {response.status_code}")
                                    if response.status_code < 300:
                                        logger.info("Successfully sent response via response_url")
                                        return
                                    else:
                                        logger.error(f"Response URL error: {response.text[:200]}")
                                except Exception as resp_error:
                                    logger.error(f"Response URL fallback failed: {resp_error}")
                            
                            # Get the user's DM channel to send instructions
                            try:
                                dm_channel = client.conversations_open(users=user_id)
                                if dm_channel and dm_channel.get('ok') and dm_channel.get('channel', {}).get('id'):
                                    dm_id = dm_channel['channel']['id']
                                    
                                    # Send instructions via DM with channel information
                                    client.chat_postMessage(
                                        channel=dm_id,
                                        text=f"I couldn't post your Charlotte analysis in <#{channel_id}> because I'm not in that channel. Please invite me using `/invite @security_agent` in that channel, then try again."
                                    )
                                    
                                    # Also send a simplified version of the analysis in the DM
                                    client.chat_postMessage(
                                        channel=dm_id,
                                        text=f"*Here's your analysis (simplified version):*\n\n*Your prompt:*\n{user_prompt[:300]}{'...' if len(user_prompt) > 300 else ''}\n\n*Analysis:*\n{result[:1500]}{'...' if len(result) > 1500 else ''}"
                                    )
                                    
                                    logger.info(f"Sent DM to user {user_id} with invitation instructions and simplified analysis")
                                    return
                                else:
                                    logger.error(f"Could not open DM with user: {dm_channel}")
                            except Exception as dm_error:
                                logger.error(f"Failed to send DM: {dm_error}")
                                
                            # If DM fails, try one more ephemeral fallback
                            try:
                                # Try a different channel where the bot might be a member
                                # This is a fallback method - it depends on the bot being in at least one channel
                                channels_list = client.conversations_list(types="public_channel")
                                for channel in channels_list.get('channels', []):
                                    try:
                                        client.chat_postEphemeral(
                                            channel=channel['id'],
                                            user=user_id,
                                            text=f"I couldn't post your Charlotte analysis in <#{channel_id}> because I'm not in that channel. Please invite me using `/invite @security_agent` in that channel, then try again."
                                        )
                                        logger.info(f"Sent ephemeral message in fallback channel {channel['id']}")
                                        return
                                    except:
                                        continue
                            except Exception as fallback_error:
                                logger.error(f"Final fallback attempt failed: {fallback_error}")
                            
                        except Exception as invite_error:
                            logger.error(f"Failed to handle not_in_channel error: {invite_error}")
                    
                    # Try using ephemeral message as a last resort
                    try:
                        logger.info("Attempting to post ephemeral message")
                        client.chat_postEphemeral(
                            channel=channel_id,
                            user=user_id,
                            blocks=blocks[:10],  # Truncate blocks in case of size issues
                            text="Charlotte's Security Investigation Steps could not be displayed with full formatting."
                        )
                        logger.info("Posted ephemeral fallback message")
                    except Exception as final_error:
                        logger.error(f"Final fallback attempt failed: {final_error}")
                
                # Trigger Salesforce flow if configured
                if os.getenv("HEROKU_APPLINK_URL"):
                    try:
                        # Log the Heroku AppLink URL (truncated for security)
                        applink_url = os.getenv("HEROKU_APPLINK_URL")
                        logger.info(f"Attempting to trigger Salesforce flow at {applink_url[:20]}...{applink_url[-10:] if applink_url else 'None'}")
                        
                        # Create a more concise payload to avoid size issues
                        salesforce_payload = {
                            "incident_data": {
                                "source": "Security Agent",
                                "type": "Investigation",
                                "details": {
                                    "article_id": article_id,
                                    "prompt": user_prompt[:500] if user_prompt else "",  # Truncate for reasonable size
                                    "channel_id": channel_id,
                                    "thread_ts": thread_ts,
                                    "timestamp": datetime.now().isoformat()
                                }
                            },
                            "query_text": user_prompt[:100] if user_prompt else ""  # Short version for indexing
                        }
                        
                        # Check if the endpoint exists before sending
                        logger.info("Checking if Salesforce endpoint exists...")
                        endpoint_url = f"{os.getenv('HEROKU_APPLINK_URL')}/api/agentforce/security-triage"
                        
                        # First try a HEAD request to see if endpoint exists
                        head_response = requests.head(
                            endpoint_url,
                            headers={
                                "Authorization": f"Bearer {os.getenv('HEROKU_APPLINK_TOKEN')}",
                                "Content-Type": "application/json"
                            },
                            timeout=3
                        )
                        
                        if head_response.status_code >= 400:
                            logger.warning(f"Salesforce endpoint may not exist (status: {head_response.status_code})")
                        
                        # Send the actual payload
                        logger.info(f"Sending payload to Salesforce endpoint")
                        response = requests.post(
                            endpoint_url,
                            json=salesforce_payload,
                            headers={
                                "Authorization": f"Bearer {os.getenv('HEROKU_APPLINK_TOKEN')}",
                                "Content-Type": "application/json"
                            },
                            timeout=5
                        )
                        
                        # Log detailed response information
                        logger.info(f"Salesforce AgentForce trigger status: {response.status_code}")
                        if response.status_code >= 400:
                            logger.error(f"Salesforce API error: {response.text[:200] if response.text else 'No response body'}")
                            
                            # If endpoint not found, log environment configuration
                            if response.status_code == 404:
                                logger.error("Salesforce endpoint not found. Please verify HEROKU_APPLINK_URL is correct.")
                                logger.error(f"Current endpoint URL: {endpoint_url}")
                        else:
                            logger.info("Salesforce trigger succeeded")
                            
                    except requests.exceptions.ConnectionError as conn_error:
                        logger.error(f"Connection error to Salesforce endpoint: {conn_error}")
                        logger.error("Check if the Heroku AppLink server is running and accessible")
                    except Exception as sf_error:
                        logger.error(f"Error triggering Salesforce flow: {sf_error}")
                        logger.error(traceback.format_exc())
                else:
                    logger.warning("HEROKU_APPLINK_URL not configured, skipping Salesforce integration")
                
            except Exception as e:
                logger.error(f"Error in charlotte_modal_handler: {e}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                
                # Try to send an ephemeral message to the user
                if channel_id and user_id:
                    try:
                        client.chat_postEphemeral(
                            channel=channel_id,
                            user=user_id,
                            text=f"I encountered an error processing your request: {str(e)}"
                        )
                    except Exception as final_error:
                        logger.error(f"Failed completely - could not even send error message: {final_error}")
        
        # Register handler for Salesforce case creation button
        def create_salesforce_case_handler(ack, body, client):
            ack()
            logger.info("Create Salesforce Case button clicked")
            
            try:
                # Extract data from button payload
                value_data = json.loads(body["actions"][0]["value"])
                initial_command = value_data.get("initial_command", "")
                user_prompt = value_data.get("user_prompt", "")
                steps = value_data.get("steps", "")
                article_id = value_data.get("article_id", "")
                channel_id = value_data.get("channel_id")
                message_ts = value_data.get("message_ts")
                thread_ts = value_data.get("thread_ts")
                reply_ts = value_data.get("reply_ts")
                
                # Get user info who clicked the button
                user_id = body["user"]["id"]
                
                # Determine which message to thread from
                target_ts = reply_ts or thread_ts or message_ts
                
                logger.info(f"Creating Salesforce case with data from {channel_id}, thread {target_ts}")
                
                # Open a modal to confirm case creation details
                client.views_open(
                    trigger_id=body["trigger_id"],
                    view={
                        "type": "modal",
                        "callback_id": "salesforce_case_modal",
                        "title": {
                            "type": "plain_text",
                            "text": "Create Security Case"
                        },
                        "submit": {
                            "type": "plain_text",
                            "text": "Create Case"
                        },
                        "close": {
                            "type": "plain_text",
                            "text": "Cancel"
                        },
                        "private_metadata": json.dumps({
                            "initial_command": initial_command,
                            "user_prompt": user_prompt,
                            "steps": steps,
                            "article_id": article_id,
                            "channel_id": channel_id,
                            "message_ts": message_ts,
                            "thread_ts": thread_ts,
                            "reply_ts": reply_ts
                        }),
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": "*Security Case Details*"
                                }
                            },
                            {
                                "type": "input",
                                "block_id": "case_title_block",
                                "element": {
                                    "type": "plain_text_input",
                                    "action_id": "case_title_input",
                                    "initial_value": f"Security Investigation: {user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}",
                                    "placeholder": {
                                        "type": "plain_text",
                                        "text": "Enter case title"
                                    }
                                },
                                "label": {
                                    "type": "plain_text",
                                    "text": "Case Title"
                                }
                            },
                            {
                                "type": "input",
                                "block_id": "case_priority_block",
                                "element": {
                                    "type": "static_select",
                                    "action_id": "case_priority_input",
                                    "options": [
                                        {
                                            "text": {
                                                "type": "plain_text",
                                                "text": "High"
                                            },
                                            "value": "high"
                                        },
                                        {
                                            "text": {
                                                "type": "plain_text",
                                                "text": "Medium"
                                            },
                                            "value": "medium"
                                        },
                                        {
                                            "text": {
                                                "type": "plain_text",
                                                "text": "Low"
                                            },
                                            "value": "low"
                                        }
                                    ],
                                    "initial_option": {
                                        "text": {
                                            "type": "plain_text",
                                            "text": "Medium"
                                        },
                                        "value": "medium"
                                    }
                                },
                                "label": {
                                    "type": "plain_text",
                                    "text": "Priority"
                                }
                            },
                            {
                                "type": "input",
                                "block_id": "case_notes_block",
                                "element": {
                                    "type": "plain_text_input",
                                    "multiline": True,
                                    "action_id": "case_notes_input",
                                    "initial_value": "Additional case notes or context",
                                    "placeholder": {
                                        "type": "plain_text",
                                        "text": "Add any additional notes about this case"
                                    }
                                },
                                "label": {
                                    "type": "plain_text",
                                    "text": "Notes"
                                }
                            }
                        ]
                    }
                )
                
            except Exception as e:
                logger.error(f"Error handling Create Salesforce Case button: {e}")
                logger.error(traceback.format_exc())
                
                # Try to send an error message
                if channel_id and user_id:
                    try:
                        client.chat_postEphemeral(
                            channel=channel_id,
                            user=user_id,
                            text=f"I encountered an error creating the Salesforce case: {str(e)}"
                        )
                    except Exception as final_error:
                        logger.error(f"Could not send error message: {final_error}")
        
        # Register handler for Salesforce case creation modal submission
        def salesforce_case_modal_handler(ack, body, client, view):
            ack()
            logger.info("Salesforce case creation modal submitted")
            
            try:
                # Extract data from the submission
                private_metadata = json.loads(view["private_metadata"])
                initial_command = private_metadata.get("initial_command", "")
                user_prompt = private_metadata.get("user_prompt", "")
                steps = private_metadata.get("steps", "")
                article_id = private_metadata.get("article_id", "")
                channel_id = private_metadata.get("channel_id")
                message_ts = private_metadata.get("message_ts")
                thread_ts = private_metadata.get("thread_ts")
                reply_ts = private_metadata.get("reply_ts")
                
                # Extract form values
                case_title = view["state"]["values"]["case_title_block"]["case_title_input"]["value"]
                case_priority = view["state"]["values"]["case_priority_block"]["case_priority_input"]["selected_option"]["value"]
                case_notes = view["state"]["values"]["case_notes_block"]["case_notes_input"]["value"]
                
                # Get user who submitted the form
                user_id = body["user"]["id"]
                
                # Determine which message to thread from
                target_ts = reply_ts or thread_ts or message_ts
                
                # Prepare the payload for Salesforce
                salesforce_payload = {
                    "case_data": {
                        "source": "Security Agent",
                        "type": "Security Investigation",
                        "title": case_title,
                        "priority": case_priority,
                        "notes": case_notes,
                        "details": {
                            "initial_command": initial_command,
                            "article_id": article_id,
                            "prompt": user_prompt,  # This might be truncated from button data
                            "steps": steps,         # This might be truncated from button data
                            "channel_id": channel_id,
                            "thread_ts": target_ts,
                            "slack_user_id": user_id,
                            "created_at": datetime.now().isoformat()
                        }
                    }
                }
                
                # Send the payload to Salesforce via Heroku applink
                if os.getenv("HEROKU_APPLINK_URL"):
                    try:
                        # Log the AppLink URL (truncated for security)
                        applink_url = os.getenv("HEROKU_APPLINK_URL")
                        logger.info(f"Creating Salesforce case at {applink_url[:20]}...{applink_url[-10:] if applink_url else 'None'}")
                        
                        # Prepare the URL
                        endpoint_url = f"{applink_url}/api/agentforce/security-case"
                        
                        # First check if endpoint exists (HEAD request)
                        try:
                            logger.info(f"Checking if endpoint exists: {endpoint_url}")
                            head_response = requests.head(
                                endpoint_url,
                                headers={
                                    "Authorization": f"Bearer {os.getenv('HEROKU_APPLINK_TOKEN')}",
                                    "Content-Type": "application/json"
                                },
                                timeout=3
                            )
                            
                            if head_response.status_code >= 400:
                                logger.warning(f"Salesforce case endpoint may not exist (status: {head_response.status_code})")
                        except Exception as head_error:
                            logger.warning(f"Error checking endpoint: {head_error}")
                        
                        # Send the actual case creation request
                        logger.info("Sending case creation request to Salesforce")
                        response = requests.post(
                            endpoint_url,
                            json=salesforce_payload,
                            headers={
                                "Authorization": f"Bearer {os.getenv('HEROKU_APPLINK_TOKEN')}",
                                "Content-Type": "application/json"
                            },
                            timeout=10
                        )
                        
                        logger.info(f"Salesforce case creation status: {response.status_code}")
                        
                        # Detailed logging for non-success responses
                        if response.status_code >= 400:
                            logger.error(f"Salesforce API error: {response.text[:200] if response.text else 'No response body'}")
                            if response.status_code == 404:
                                logger.error("Salesforce endpoint not found. Check HEROKU_APPLINK_URL configuration.")
                        
                        # Get the case number from the response if available
                        case_number = None
                        try:
                            response_data = response.json()
                            case_number = response_data.get("case_number")
                            logger.info(f"Created Salesforce case number: {case_number}")
                        except:
                            logger.warning("Could not extract case number from response")
                        
                        # Send confirmation message to the channel
                        if response.status_code < 300:
                            confirmation_text = f"✅ Security case {case_number or ''} created successfully in Salesforce."
                            if case_number:
                                confirmation_text += f" Case #{case_number}"
                        else:
                            confirmation_text = f"⚠️ There was an issue creating the Salesforce case. Status: {response.status_code}"
                        
                        # Post confirmation as a thread reply
                        if target_ts:
                            client.chat_postMessage(
                                channel=channel_id,
                                thread_ts=target_ts,
                                text=confirmation_text
                            )
                        else:
                            client.chat_postMessage(
                                channel=channel_id,
                                text=confirmation_text
                            )
                    except Exception as sf_error:
                        logger.error(f"Error creating Salesforce case: {sf_error}")
                        logger.error(traceback.format_exc())
                        
                        # Send error message
                        if channel_id:
                            error_text = f"⚠️ Error creating Salesforce case: {str(sf_error)}"
                            if target_ts:
                                client.chat_postMessage(
                                    channel=channel_id,
                                    thread_ts=target_ts,
                                    text=error_text
                                )
                            else:
                                client.chat_postMessage(
                                    channel=channel_id,
                                    text=error_text
                                )
                else:
                    logger.warning("HEROKU_APPLINK_URL not configured, cannot create Salesforce case")
                    
                    # Send warning message
                    if channel_id:
                        warning_text = "⚠️ Salesforce integration is not configured. Contact your system administrator."
                        if target_ts:
                            client.chat_postMessage(
                                channel=channel_id,
                                thread_ts=target_ts,
                                text=warning_text
                            )
                        else:
                            client.chat_postMessage(
                                channel=channel_id,
                                text=warning_text
                            )
                            
            except Exception as e:
                logger.error(f"Error in salesforce_case_modal_handler: {e}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                
                # Try to send an error message
                if channel_id:
                    try:
                        client.chat_postEphemeral(
                            channel=channel_id,
                            user=user_id,
                            text=f"I encountered an error creating the Salesforce case: {str(e)}"
                        )
                    except Exception as final_error:
                        logger.error(f"Could not send error message: {final_error}")
        
        # Register action and view handlers
        self.app.action("create_salesforce_case")(create_salesforce_case_handler)
        self.app.view("salesforce_case_modal")(salesforce_case_modal_handler)
        
        self.app.view("charlotte_modal")(charlotte_modal_handler)
        
        logger.info("Successfully registered all handlers")
    
    def handle_security_command_wrapper(self, ack, body, respond):
        """Non-async wrapper for the async security command handler."""
        # Detailed logging for debugging dispatch_failed errors
        logger.info(f"Received /security command: {body.get('command')} {body.get('text', '')}")
        logger.info(f"Command body: {json.dumps(body)[:500]}...")
        
        try:
            # First acknowledge the request
            logger.info("Attempting to acknowledge Slack command...")
            ack()
            logger.info("Successfully acknowledged Slack command")
        
            # Store the response_url for later use
            response_url = body.get("response_url")
            if response_url:
                logger.info(f"Captured response_url from slash command: {response_url[:30]}...")
            else:
                logger.warning("No response_url found in slash command body")
        
            # Store the original command
            original_command = body.get("command", "") + " " + body.get("text", "").strip()
            logger.info(f"Original command: {original_command}")
            
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
                        # Format results using blocks to include the Ask Charlotte button
                        formatted_blocks = self.security_agent._format_slack_blocks(
                            result["original_results"], 
                            response_url=response_url,
                            initial_command=original_command
                        )
                        
                        # Send blocks using the respond function
                        respond(
                            blocks=formatted_blocks,
                            text=f"Found {len(result['original_results'])} relevant security knowledge articles",
                            response_type="in_channel"
                        )
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
        except Exception as e:
            logger.error(f"Error handling security command: {e}")
            logger.error(traceback.format_exc())
            respond(text="I encountered an error processing your request. Please try again later.")
    
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
            logger.info(f"Using app token: {self.slack_app_token[:5]}...{self.slack_app_token[-5:] if self.slack_app_token else 'None'}")
            logger.info(f"Using bot token: {self.slack_bot_token[:5]}...{self.slack_bot_token[-5:] if self.slack_bot_token else 'None'}")
            
            # Verify token validity before starting
            try:
                test_auth = self.client.auth_test()
                logger.info(f"Auth test successful: {test_auth}")
            except Exception as auth_error:
                logger.error(f"Auth test failed: {auth_error}")
                raise
                
            handler = SocketModeHandler(self.app, self.slack_app_token)
            handler.start()
        except Exception as e:
            logger.error(f"Error starting Slack app: {str(e)}")
            logger.error(traceback.format_exc())
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