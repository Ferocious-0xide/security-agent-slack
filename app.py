import logging
from security_agent import SecurityAgent
from slack_handler import SlackHandler
import os
from dotenv import load_dotenv
import traceback

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    try:
        # Load environment variables
        load_dotenv()
        
        # Initialize Security Agent
        security_agent = SecurityAgent()
        
        # Initialize Slack Handler
        slack_handler = SlackHandler(security_agent)
        
        # Start the Slack app
        logger.info("Starting Security Agent with Slack integration...")
        slack_handler.start()
        
    except Exception as e:
        logger.error(f"Error starting application: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

if __name__ == "__main__":
    main() 