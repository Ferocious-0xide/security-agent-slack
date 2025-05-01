import os
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import anthropic
import requests
from datetime import datetime
import logging
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import numpy as np
from pgvector.psycopg2 import register_vector
import traceback
from dotenv import load_dotenv
import urllib3
import random
from fastapi.responses import JSONResponse

# Disable SSL warnings
urllib3.disable_warnings()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Debug environment variables
logger.info("Checking environment variables...")
api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    logger.error("ANTHROPIC_API_KEY not found in environment variables")
    logger.info("Current environment variables:")
    for key in ["ANTHROPIC_API_KEY", "DATABASE_URL", "CHARLOTTE_SERVICE_KEY"]:
        logger.info(f"{key}: {'Set' if os.getenv(key) else 'Not set'}")
    raise ValueError("ANTHROPIC_API_KEY must be set in environment variables")

# Initialize Anthropic client
anthropic_client = anthropic.Client(api_key=api_key)
logger.info("Anthropic client initialized successfully")

# Initialize FastAPI app
app = FastAPI(title="Mock Charlotte RAG Service")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
def get_db_connection():
    try:
        conn = psycopg2.connect(
            os.getenv("DATABASE_URL"),
            cursor_factory=RealDictCursor
        )
        register_vector(conn)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

# Models
class Query(BaseModel):
    query: str = Field(..., description="The query to process")
    max_tokens: Optional[int] = Field(500, description="Maximum tokens for response")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context for the query")

class Response(BaseModel):
    answer: str = Field(..., description="The generated answer")
    confidence: float = Field(..., description="Confidence score of the answer")
    sources: List[Dict[str, Any]] = Field(..., description="List of sources used")
    timestamp: str = Field(..., description="Timestamp of the response")

class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message")
    details: Optional[str] = Field(None, description="Additional error details")
    timestamp: str = Field(..., description="Timestamp of the error")

# Additional Models
class SlackEvent(BaseModel):
    type: str = Field(..., description="Type of Slack event")
    event: Optional[Dict[str, Any]] = Field(None, description="Event data")
    team_id: Optional[str] = Field(None, description="Slack team ID")
    api_app_id: Optional[str] = Field(None, description="Slack app ID")
    event_id: Optional[str] = Field(None, description="Event unique ID")
    event_time: Optional[int] = Field(None, description="Event timestamp")
    challenge: Optional[str] = Field(None, description="Challenge for URL verification")

class SalesforceIncident(BaseModel):
    id: Optional[str] = Field(None, description="Internal UUID")
    salesforce_id: str = Field(..., description="Salesforce incident ID")
    title: str = Field(..., description="Incident title")
    description: str = Field(..., description="Incident description")
    severity: str = Field(..., description="Incident severity")
    status: str = Field(..., description="Incident status")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")

class StatusUpdate(BaseModel):
    component: str = Field(..., description="Component name")
    status: str = Field(..., description="Current status")
    message: Optional[str] = Field(None, description="Status message")
    last_updated: str = Field(..., description="Last update timestamp")

# Helper functions
def get_embedding(text: str) -> List[float]:
    """Get embedding for text using Heroku managed inference addon."""
    try:
        # For demo purposes, return a simple placeholder embedding
        # This avoids needing the external INFERENCE_API_URL 
        placeholder_embedding = [0.1] * 1024
        return placeholder_embedding
    except Exception as e:
        logger.error(f"Embedding generation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate embedding")

def format_slack_response(response: Response) -> Dict[str, Any]:
    """Format response for Slack."""
    confidence_emoji = "🟢" if response.confidence > 0.8 else "🟡" if response.confidence > 0.5 else "🔴"
    
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Analysis:*\n{response.answer}"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{confidence_emoji} Confidence: {response.confidence:.2%}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"🕒 {response.timestamp}"
                }
            ]
        }
    ]

    if response.sources:
        sources_text = "\n".join([f"• {source['title']}" for source in response.sources[:3]])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Sources:*\n{sources_text}"
            }
        })

    return {"blocks": blocks}

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

# API endpoints
@app.post("/v1/chat/completions", response_model=Response)
async def chat_completions(query: Query, request: Request):
    """Process a query and return a response."""
    try:
        # Validate API key
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        
        api_key = auth_header.split(" ")[1]
        if api_key != os.getenv("CHARLOTTE_SERVICE_KEY"):
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Get query embedding
        query_embedding = get_embedding(query.query)
        
        # Search for relevant documents
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Cast the embedding to vector type
                cur.execute("""
                    SELECT title, content, 
                           1 - (embedding <=> %s::vector) as similarity
                    FROM documents
                    WHERE embedding IS NOT NULL
                    ORDER BY similarity DESC
                    LIMIT 5
                """, (query_embedding,))
                results = cur.fetchall()

        # Format context
        context = "\n\n".join([f"Title: {r['title']}\nContent: {r['content']}" for r in results])
        
        # Generate response using Claude
        try:
            completion = anthropic_client.completion(
                prompt=f"{anthropic.HUMAN_PROMPT} Context:\n{context}\n\nQuery: {query.query}{anthropic.AI_PROMPT}",
                model="claude-3-sonnet-20240229",
                max_tokens_to_sample=query.max_tokens,
                temperature=0,
            )
            
            answer = completion.completion
            confidence = min(1.0, len(context) / 1000)  # Simple confidence metric
            
            return Response(
                answer=answer,
                confidence=confidence,
                sources=[{"title": r["title"]} for r in results],
                timestamp=datetime.now().isoformat()
            )
            
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise HTTPException(status_code=500, detail="Failed to generate response")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/v1/slack/events")
async def slack_events(event: SlackEvent, request: Request):
    """Handle Slack events."""
    try:
        # Validate Slack signature (implementation needed)
        auth_header = request.headers.get("X-Slack-Signature")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Invalid or missing Slack signature")
        
        # Process different event types
        if event.type == "url_verification":
            if event.challenge:
                return {"challenge": event.challenge}
            raise HTTPException(status_code=400, detail="Missing challenge parameter")
        
        # Handle message events
        if event.type == "event_callback" and event.event and event.event.get("type") == "message":
            # Process message and generate response
            query = Query(query=event.event.get("text", ""))
            # Create a new request with the required headers
            headers = {"Authorization": f"Bearer {os.getenv('CHARLOTTE_SERVICE_KEY')}"}
            # Process directly using the chat_completions endpoint
            response = await chat_completions(query, Request(scope={"type": "http", "headers": [(b"authorization", headers["Authorization"].encode())]}))
            return format_slack_response(response)
        
        return {"ok": True}
    except HTTPException as e:
        logger.error(f"Slack event processing error: {e}")
        raise e
    except Exception as e:
        logger.error(f"Slack event processing error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process Slack event")

@app.post("/v1/salesforce/incidents")
async def create_incident(incident: SalesforceIncident, request: Request):
    """Create or update a Salesforce incident."""
    try:
        # Validate API key
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        
        api_key = auth_header.split(" ")[1]
        if api_key != os.getenv("CHARLOTTE_SERVICE_KEY"):
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        # Store incident in database
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO incidents (
                        salesforce_id, title, description, severity, status, 
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (salesforce_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at
                    RETURNING id
                """, (
                    incident.salesforce_id, incident.title, incident.description,
                    incident.severity, incident.status, incident.created_at,
                    incident.updated_at
                ))
                result = cur.fetchone()
                conn.commit()
        
        return {"id": result["id"], "status": "success"}
    except HTTPException as e:
        logger.error(f"Salesforce incident creation error: {e}")
        raise e
    except Exception as e:
        logger.error(f"Salesforce incident creation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create/update incident")

@app.get("/v1/salesforce/incidents/{incident_id}")
async def get_incident(incident_id: str, request: Request):
    """Get Salesforce incident details."""
    try:
        # Validate API key
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        
        api_key = auth_header.split(" ")[1]
        if api_key != os.getenv("CHARLOTTE_SERVICE_KEY"):
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        # Retrieve incident from database
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        id, salesforce_id, title, description, 
                        severity, status, 
                        created_at::text, updated_at::text
                    FROM incidents 
                    WHERE salesforce_id = %s
                """, (incident_id,))
                result = cur.fetchone()
                
        if not result:
            raise HTTPException(status_code=404, detail="Incident not found")
        
        return SalesforceIncident(**result)
    except HTTPException as e:
        logger.error(f"Salesforce incident retrieval error: {e}")
        raise e
    except Exception as e:
        logger.error(f"Salesforce incident retrieval error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve incident")

@app.get("/v1/status")
async def get_status():
    """Get system status for all components."""
    try:
        components = []
        
        # Check database connection
        try:
            with get_db_connection() as conn:
                components.append(StatusUpdate(
                    component="database",
                    status="operational",
                    message="Connected successfully",
                    last_updated=datetime.now().isoformat()
                ))
        except Exception as e:
            components.append(StatusUpdate(
                component="database",
                status="error",
                message=str(e),
                last_updated=datetime.now().isoformat()
            ))
        
        # Check Anthropic API
        try:
            anthropic_client.completion(
                prompt=f"{anthropic.HUMAN_PROMPT} Hi{anthropic.AI_PROMPT}",
                model="claude-3-sonnet-20240229",
                max_tokens_to_sample=10,
            )
            components.append(StatusUpdate(
                component="anthropic",
                status="operational",
                message="API responding",
                last_updated=datetime.now().isoformat()
            ))
        except Exception as e:
            components.append(StatusUpdate(
                component="anthropic",
                status="error",
                message=str(e),
                last_updated=datetime.now().isoformat()
            ))
        
        return {"components": components}
    except Exception as e:
        logger.error(f"Status check error: {e}")
        raise HTTPException(status_code=500, detail="Failed to check system status")

@app.get("/trigger-alert")
async def trigger_alert(channel: Optional[str] = None, alert_type: Optional[str] = None):
    """Trigger a mock security alert in Slack."""
    try:
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

@app.get("/health")
async def health_check():
    """Enhanced health check endpoint."""
    try:
        # Check all critical components
        status = await get_status()
        
        # Calculate overall health
        is_healthy = all(component.status == "operational" 
                        for component in status["components"])
        
        return {
            "status": "healthy" if is_healthy else "degraded",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
            "components": status["components"]
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))