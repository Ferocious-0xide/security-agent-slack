#!/usr/bin/env python
import os
import logging
import json
import random
import requests
from datetime import datetime
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def send_slack_alert(webhook_url, channel, message, alert_type="info"):
    """Send an alert message to Slack via webhook."""
    
    # Set color based on alert type
    color = "#2EB67D"  # Green for info
    if alert_type == "warning":
        color = "#ECB22E"  # Yellow for warning
    elif alert_type == "critical":
        color = "#E01E5A"  # Red for critical

    # Create Slack message payload
    payload = {
        "channel": channel,
        "username": "Security Alert Bot",
        "icon_emoji": ":rotating_light:",
        "attachments": [
            {
                "color": color,
                "pretext": ":rotating_light: *SECURITY ALERT*",
                "title": "Potential Security Concern Detected",
                "text": message,
                "footer": f"Alert Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "footer_icon": "https://platform.slack-edge.com/img/default_application_icon.png"
            }
        ]
    }

    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            logger.info(f"Alert sent successfully to {channel}")
            return True
        else:
            logger.error(f"Failed to send alert: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending alert: {str(e)}")
        return False

def generate_random_alert():
    """Generate a random security alert suggesting use of the security search command."""
    
    alert_templates = [
        "Potential data exfiltration activity detected. Use `/security search data exfiltration` for best practices and guidance.",
        "Unusual network traffic patterns observed. Consider running `/security search network segmentation` for security recommendations.",
        "Multiple failed login attempts detected. Please check `/security search access control` for security guidance.",
        "Suspicious email activity detected. Run `/security search email security` for best practices.",
        "Unusual cloud resource access detected. Use `/security search cloud security` for recommendations.",
        "Potential malware activity detected. Check `/security search endpoint detection` for response guidance.",
        "Configuration drift detected in critical systems. Run `/security search secure configuration` for best practices.",
        "Suspicious privileged account activity observed. Use `/security search privileged access` for security guidance."
    ]
    
    return random.choice(alert_templates)

def main():
    """Main function to send a mock security alert."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    channel = os.getenv("SLACK_ALERT_CHANNEL", "#security-alerts")
    
    if not webhook_url:
        logger.error("SLACK_WEBHOOK_URL is not set in environment variables")
        return False
    
    alert_message = generate_random_alert()
    alert_type = random.choice(["info", "warning", "critical"])
    
    return send_slack_alert(webhook_url, channel, alert_message, alert_type)

if __name__ == "__main__":
    main() 