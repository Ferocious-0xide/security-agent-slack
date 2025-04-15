import os
import time
import schedule
import threading
from datetime import datetime
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import requests
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class SecurityAgent:
    def __init__(self):
        self.slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
        self.slack_channel = os.getenv("SLACK_CHANNEL_ID")
        self.charlotte_api_key = os.getenv("CHARLOTTE_API_KEY")
        self.charlotte_endpoint = os.getenv("CHARLOTTE_API_ENDPOINT")
        
    def query_charlotte_ai(self, query):
        """Query CrowdStrike Charlotte AI for security insights."""
        try:
            headers = {
                "Authorization": f"Bearer {self.charlotte_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "query": query,
                "max_tokens": 500
            }
            
            response = requests.post(
                self.charlotte_endpoint,
                headers=headers,
                json=payload
            )
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error querying Charlotte AI: {e}")
            return None

    def generate_prompt_suggestion(self):
        """Generate a prompt suggestion based on common security scenarios."""
        # Example queries to Charlotte AI for security insights
        queries = [
            "What are the most critical security alerts to focus on for junior analysts?",
            "What are common investigation steps for suspicious process creation events?",
            "How to effectively triage potential data exfiltration alerts?",
            "What are best practices for investigating potential lateral movement?"
        ]
        
        # Randomly select a query and get insights
        query = queries[int(time.time()) % len(queries)]
        response = self.query_charlotte_ai(query)
        
        if not response:
            return "Unable to generate suggestion at this time. Please check system logs."
            
        return f"*Security Analysis Prompt Suggestion*\nQuery: {query}\nInsight: {response['answer']}"

    def post_to_slack(self, message):
        """Post a message to the specified Slack channel."""
        try:
            self.slack_client.chat_postMessage(
                channel=self.slack_channel,
                text=message,
                mrkdwn=True
            )
            logger.info("Successfully posted suggestion to Slack")
        except SlackApiError as e:
            logger.error(f"Error posting to Slack: {e}")

    def run_suggestion_cycle(self):
        """Run a complete suggestion cycle."""
        suggestion = self.generate_prompt_suggestion()
        self.post_to_slack(suggestion)

def run_scheduler():
    """Run the scheduler in a separate thread."""
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    agent = SecurityAgent()
    interval = int(os.getenv("SUGGESTION_INTERVAL_MINUTES", 30))
    
    # Schedule regular suggestions
    schedule.every(interval).minutes.do(agent.run_suggestion_cycle)
    
    # Run the first suggestion immediately
    agent.run_suggestion_cycle()
    
    # Start the scheduler in a separate thread
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.start()
    
    logger.info(f"Security Agent started. Posting suggestions every {interval} minutes.")

if __name__ == "__main__":
    main() 