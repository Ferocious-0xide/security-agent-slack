import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import requests
from dotenv import load_dotenv
import logging
from typing import Dict, Any, Optional
import json
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Slack Bolt app
app = App(token=os.environ["SLACK_BOT_TOKEN"])

class SecurityBot:
    def __init__(self):
        self.service_url = os.environ['CHARLOTTE_SERVICE_URL']
        self.service_key = os.environ['CHARLOTTE_SERVICE_KEY']
        self.command_handlers = {
            "analyze": self.handle_analysis,
            "incident": self.handle_incident,
            "help": self.handle_help
        }

    def query_charlotte_service(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Query our Heroku-hosted Charlotte service with optional context."""
        try:
            payload = {
                "query": query,
                "max_tokens": 500,
                "context": context or {}
            }
            
            response = requests.post(
                f"{self.service_url}/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.service_key}"}
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error querying Charlotte service: {e}")
            return {"error": str(e)}

    def format_response(self, query: str, response: Dict[str, Any], command: Optional[str] = None) -> Dict[str, Any]:
        """Format the response into Slack blocks."""
        if "error" in response:
            return {
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Error Processing Request:*\n{response['error']}"
                        }
                    }
                ]
            }

        confidence = response.get('confidence', 'N/A')
        confidence_emoji = "🟢" if confidence > 0.8 else "🟡" if confidence > 0.5 else "🔴"
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{command.title() if command else 'Query'}:*\n{query}\n\n*Analysis:*\n{response['answer']}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"{confidence_emoji} Confidence: {confidence:.2%}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                ]
            }
        ]

        # Add action buttons for follow-up
        if command == "analyze":
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Create Incident",
                            "emoji": True
                        },
                        "value": f"create_incident_{query[:50]}",
                        "action_id": "create_incident"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Get More Details",
                            "emoji": True
                        },
                        "value": query,
                        "action_id": "get_details"
                    }
                ]
            })

        return {"blocks": blocks}

    def handle_analysis(self, query: str, say) -> None:
        """Handle security analysis requests."""
        response = self.query_charlotte_service(query)
        formatted_response = self.format_response(query, response, "analysis")
        say(**formatted_response)

    def handle_incident(self, query: str, say) -> None:
        """Handle incident creation requests."""
        # TODO: Integrate with Salesforce
        response = self.query_charlotte_service(query, {"action": "create_incident"})
        formatted_response = self.format_response(query, response, "incident")
        say(**formatted_response)

    def handle_help(self, query: str, say) -> None:
        """Handle help requests."""
        help_text = """
*Available Commands:*
• `/security analyze <query>` - Analyze a security event or query
• `/security incident <description>` - Create a new security incident
• `/security help` - Show this help message

*Examples:*
• `/security analyze suspicious login attempts from unknown IP`
• `/security incident potential data exfiltration detected`
        """
        say(blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": help_text
            }
        }])

# Initialize the bot
security_bot = SecurityBot()

@app.event("app_mention")
def handle_mention(event, say):
    """Handle when the bot is mentioned in a channel."""
    try:
        query = event['text'].split(">", 1)[1].strip()
        security_bot.handle_analysis(query, say)
    except Exception as e:
        logger.error(f"Error handling mention: {e}")
        say("Sorry, I encountered an error processing your request.")

@app.command("/security")
def handle_security_command(ack, command, say):
    """Handle /security slash command."""
    ack()
    try:
        # Split command into action and query
        parts = command['text'].split(maxsplit=1)
        action = parts[0].lower() if parts else "help"
        query = parts[1] if len(parts) > 1 else ""

        # Get the appropriate handler
        handler = security_bot.command_handlers.get(action, security_bot.handle_help)
        handler(query, say)
        
    except Exception as e:
        logger.error(f"Error handling security command: {e}")
        say("Sorry, I encountered an error processing your security query.")

@app.action("create_incident")
def handle_create_incident(ack, body, say):
    """Handle incident creation button clicks."""
    ack()
    try:
        query = body['actions'][0]['value'].replace('create_incident_', '')
        security_bot.handle_incident(query, say)
    except Exception as e:
        logger.error(f"Error handling incident creation: {e}")
        say("Sorry, I encountered an error creating the incident.")

@app.action("get_details")
def handle_get_details(ack, body, say):
    """Handle get more details button clicks."""
    ack()
    try:
        query = body['actions'][0]['value']
        security_bot.handle_analysis(query, say)
    except Exception as e:
        logger.error(f"Error handling details request: {e}")
        say("Sorry, I encountered an error getting more details.")

if __name__ == "__main__":
    # Start the app in Socket Mode
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start() 