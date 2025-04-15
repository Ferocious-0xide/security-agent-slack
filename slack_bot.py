import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import requests
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Slack Bolt app
app = App(token=os.environ["SLACK_BOT_TOKEN"])

def query_charlotte_service(query: str) -> dict:
    """Query our Heroku-hosted Charlotte service."""
    try:
        response = requests.post(
            f"{os.environ['CHARLOTTE_SERVICE_URL']}/v1/chat/completions",
            json={
                "query": query,
                "max_tokens": 500
            },
            headers={"Authorization": f"Bearer {os.environ['CHARLOTTE_SERVICE_KEY']}"}
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error querying Charlotte service: {e}")
        return {"error": str(e)}

@app.event("app_mention")
def handle_mention(event, say):
    """Handle when the bot is mentioned in a channel."""
    try:
        # Extract the query (remove the bot mention)
        query = event['text'].split(">", 1)[1].strip()
        
        # Query Charlotte service
        response = query_charlotte_service(query)
        
        if "error" in response:
            say(f"Error: {response['error']}")
            return
            
        # Format and send response
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Query:*\n{query}\n\n*Response:*\n{response['answer']}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Confidence: {response.get('confidence', 'N/A')}"
                    }
                ]
            }
        ]
        
        say(blocks=blocks)
        
    except Exception as e:
        logger.error(f"Error handling mention: {e}")
        say("Sorry, I encountered an error processing your request.")

@app.command("/security")
def handle_security_command(ack, command, say):
    """Handle /security slash command."""
    ack()
    try:
        query = command['text']
        
        if not query:
            say("Please provide a security question or query.")
            return
            
        response = query_charlotte_service(query)
        
        if "error" in response:
            say(f"Error: {response['error']}")
            return
            
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Security Query:*\n{query}\n\n*Analysis:*\n{response['answer']}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Confidence: {response.get('confidence', 'N/A')}"
                    }
                ]
            }
        ]
        
        say(blocks=blocks)
        
    except Exception as e:
        logger.error(f"Error handling security command: {e}")
        say("Sorry, I encountered an error processing your security query.")

if __name__ == "__main__":
    # Start the app in Socket Mode
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start() 