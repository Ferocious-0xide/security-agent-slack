import logging
from security_agent import SecurityAgent
from slack_handler import SlackHandler
import os
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Print Slack permissions warning
print("="*80)
print("WARNING: IMPORTANT SLACK PERMISSION INFORMATION")
print("="*80)
print("Your Slack app needs the following OAuth scopes to function properly:")
print("- app_mentions:read - current")
print("- chat:write - current")
print("- commands - current")
print("- channels:join - MISSING")
print("- groups:read - RECOMMENDED")
print("- im:write - RECOMMENDED") 
print("- users:read - RECOMMENDED")
print("\nTo fix the 'Ask Charlotte' functionality in channels:")
print("1. Go to api.slack.com/apps and select your Security Agent app")
print("2. Navigate to 'OAuth & Permissions'")
print("3. Under 'Scopes', add the following Bot Token Scopes:")
print("   - channels:join")
print("   - groups:read")
print("   - im:write")
print("   - users:read")
print("4. Reinstall the app to your workspace")
print("="*80)
print("\n")

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
        raise

if __name__ == "__main__":
    main() 