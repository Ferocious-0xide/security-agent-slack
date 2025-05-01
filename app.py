import logging
from security_agent import SecurityAgent
from slack_handler import SlackHandler
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends, Response
from fastapi.responses import JSONResponse
from typing import Optional
import traceback
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()

# Initialize components at module level
load_dotenv()
security_agent = SecurityAgent()
slack_handler = SlackHandler(security_agent)

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

@app.on_event("startup")
async def startup_event():
    """Start the Slack handler on app startup."""
    try:
        # Start the Slack app
        logger.info("Starting Security Agent with Slack integration...")
        slack_handler.start()
    except Exception as e:
        logger.error(f"Error starting Slack handler: {str(e)}")
        logger.error(traceback.format_exc())

@app.get("/")
async def root():
    """Root endpoint that returns a simple message."""
    return {"message": "Welcome to the Security Agent API"}

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

@app.get("/status")
async def status():
    """Status endpoint that returns component statuses."""
    components = {
        "api": "healthy",
        "slack": slack_handler.status,
        "database": security_agent.db_manager.status if hasattr(security_agent.db_manager, 'status') else "unknown",
        "anthropic": "degraded" if not security_agent.inference_client else "healthy"
    }
    
    # Check if any component is degraded or down
    overall_status = "healthy"
    for component, status in components.items():
        if status == "degraded":
            overall_status = "degraded"
        elif status == "down":
            overall_status = "down"
            break
    
    return {
        "status": overall_status,
        "components": components
    }

@app.post("/test-command")
async def test_command(request: Request):
    """Test endpoint to simulate a Slack command."""
    try:
        data = await request.json()
        command = data.get("command", "")
        
        if command.startswith("/security"):
            result = security_agent.process_command(command.replace("/security", "").strip())
            return result
        else:
            return {"message": "Invalid command format. Use '/security command'"}
    except Exception as e:
        logger.error(f"Error processing test command: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"message": f"Error: {str(e)}"}
        )

@app.get("/trigger-alert")
async def trigger_alert(channel: Optional[str] = None, alert_type: Optional[str] = None):
    """Trigger a mock security alert in Slack."""
    try:
        # Dynamically import mock_alert to avoid circular imports
        from mock_alert import send_slack_alert, generate_random_alert
        
        webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if not webhook_url:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "SLACK_WEBHOOK_URL is not set"}
            )
        
        # Use provided channel or default
        target_channel = channel or os.getenv("SLACK_ALERT_CHANNEL", "#security-alerts")
        
        # Use provided alert type or random
        alert_severity = alert_type or "info"
        if alert_severity not in ["info", "warning", "critical"]:
            alert_severity = "info"
            
        # Generate alert message
        alert_message = generate_random_alert()
        
        # Send the alert
        success = send_slack_alert(webhook_url, target_channel, alert_message, alert_severity)
        
        if success:
            return {"status": "success", "message": "Alert triggered successfully", "channel": target_channel}
        else:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Failed to send alert"}
            )
    except Exception as e:
        logger.error(f"Error triggering alert: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Error: {str(e)}"}
        )

def main():
    """Run the FastAPI application using Uvicorn."""
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == "__main__":
    main() 