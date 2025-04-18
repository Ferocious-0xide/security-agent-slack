from typing import Dict, List, Optional
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
from database import DatabaseManager
from models import SeverityLevel
import traceback
import requests
import json

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SecurityAgent:
    def __init__(self):
        load_dotenv()
        self.slack_bot_token = os.getenv('SLACK_BOT_TOKEN')
        self.slack_app_token = os.getenv('SLACK_APP_TOKEN')
        self.slack_signing_secret = os.getenv('SLACK_SIGNING_SECRET')
        self.anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        
        # Initialize components
        self._validate_environment()
        self.db_manager = DatabaseManager()
        
    def _validate_environment(self) -> None:
        """Validate that all required environment variables are set."""
        required_vars = [
            'SLACK_BOT_TOKEN',
            'SLACK_APP_TOKEN',
            'SLACK_SIGNING_SECRET',
            'DATABASE_URL',
            'EMBEDDING_URL',
            'EMBEDDING_KEY',
            'EMBEDDING_MODEL_ID',
            'ANTHROPIC_API_KEY'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    def _get_claude_analysis(self, title: str, content: str) -> str:
        """Get analysis from Claude for a specific knowledge article."""
        try:
            logger.info(f"Generating Claude analysis for: {title}")
            
            # Determine incident type from title
            incident_type = ""
            if "data exfiltration" in title.lower():
                incident_type = "data exfiltration"
            elif "privilege escalation" in title.lower():
                incident_type = "privilege escalation"
            elif "ransomware" in title.lower():
                incident_type = "ransomware"
            elif "lateral movement" in title.lower():
                incident_type = "lateral movement"
            elif "network" in title.lower():
                incident_type = "suspicious network activity"
            else:
                incident_type = "security"

            # Prepare the prompt
            prompt = f"""You are an expert security incident advisor responding to a potential {incident_type} incident.

You have access to our security knowledge base that says:
---
{content}
---

Through MCP, you also have access to:
- Current system logs related to this incident
- Historical incident response data
- Our organization's security posture metrics

Based on this contextual information, please provide:

1. Your assessment of what's happening in natural, conversational language
2. Multiple investigation angles to consider, including both obvious and non-obvious paths
3. Specific artifacts we should collect and tools to use
4. Containment measures appropriate for our environment
5. How this incident might connect to larger attack patterns we should be aware of

Your guidance should help our analysts make informed decisions quickly while maintaining a comprehensive security perspective."""
            
            # Make request to Anthropic API
            response = requests.post(
                "https://api.anthropic.com/v1/complete",
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-2",
                    "prompt": f"\n\nHuman: {prompt}\n\nAssistant:",
                    "max_tokens_to_sample": 1024,
                    "temperature": 0.7,
                    "top_p": 1,
                    "stop_sequences": ["\n\nHuman:"]
                }
            )
            
            response.raise_for_status()
            analysis = response.json()["completion"]
            logger.info("Successfully generated Claude analysis")
            return analysis
            
        except Exception as e:
            logger.error(f"Error getting Claude analysis: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.content}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return "Error generating analysis"

    def process_slack_command(self, command: Dict) -> Dict:
        """Process incoming Slack commands."""
        try:
            logger.info(f"Processing Slack command: {command}")
            command_text = command.get('text', '').lower()
            
            # Handle search queries
            if 'search' in command_text:
                # Extract the query by removing 'search' and any surrounding text
                query = command_text.replace('search', '').replace('the security knowledge base', '').strip()
                logger.info(f"Search query extracted: '{query}'")
                results = self.db_manager.search_knowledge(query)
                logger.info(f"Search returned {len(results)} results")
                
                blocks = []
                for r in results:
                    # Get analysis from Claude
                    analysis = self._get_claude_analysis(r.title, r.content)
                    
                    # Add the knowledge article
                    blocks.extend([
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": r.title
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": r.content
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "*Claude.ai Prompt:*\n" + analysis
                            }
                        },
                        {
                            "type": "divider"
                        }
                    ])
                
                return {
                    "status": "success",
                    "blocks": blocks
                }
            
            # If no specific command is found, treat it as a search query
            logger.info(f"Treating command as search query: '{command_text}'")
            results = self.db_manager.search_knowledge(command_text)
            logger.info(f"Fallback search returned {len(results)} results")
            
            blocks = []
            for r in results:
                # Get analysis from Claude
                analysis = self._get_claude_analysis(r.title, r.content)
                
                # Add the knowledge article
                blocks.extend([
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": r.title
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": r.content
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Claude.ai Prompt:*\n" + analysis
                        }
                    },
                    {
                        "type": "divider"
                    }
                ])
            
            return {
                "status": "success",
                "blocks": blocks
            }
        except Exception as e:
            logger.error(f"Error processing Slack command: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}
    
    async def process_slack_event(self, event: Dict) -> Dict:
        """Process incoming Slack events."""
        try:
            logger.info(f"Processing Slack event: {event}")
            event_type = event.get('type')
            
            if event_type == 'message':
                # Process security-related messages
                message = event.get('text', '')
                if 'security' in message.lower():
                    # Search for relevant knowledge
                    results = await self.db_manager.search_knowledge(message)
                    if results:
                        return {
                            "status": "success",
                            "message": "Found relevant security information",
                            "results": [{"title": r.title, "content": r.content} for r in results]
                        }
            
            return {"status": "success", "message": "Event processed"}
        except Exception as e:
            logger.error(f"Error processing Slack event: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    async def query_knowledge_base(self, query: str) -> List[Dict]:
        """Query the security knowledge base."""
        try:
            logger.info(f"Querying knowledge base: {query}")
            results = await self.db_manager.search_knowledge(query)
            return [{"title": r.title, "content": r.content} for r in results]
        except Exception as e:
            logger.error(f"Error querying knowledge base: {str(e)}")
            return []
    
    async def create_incident(self, incident_data: Dict) -> Dict:
        """Create a new security incident."""
        try:
            logger.info(f"Creating incident: {incident_data}")
            incident = await self.db_manager.create_incident(
                title=incident_data['title'],
                description=incident_data['description'],
                severity=SeverityLevel(incident_data['severity'].lower())
            )
            
            # Search for relevant knowledge
            results = await self.db_manager.search_knowledge(incident_data['description'])
            for knowledge in results:
                await self.db_manager.link_knowledge_to_incident(
                    incident_id=incident.id,
                    knowledge_id=knowledge.id,
                    relevance_score=90  # Default score
                )
            
            return {"status": "success", "incident_id": incident.id}
        except Exception as e:
            logger.error(f"Error creating incident: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    async def trigger_workflow(self, workflow_data: Dict) -> Dict:
        """Trigger a security workflow."""
        try:
            logger.info(f"Triggering workflow: {workflow_data}")
            incident_id = workflow_data.get('incident_id')
            if incident_id:
                incident = await self.db_manager.get_incident(incident_id)
                if incident:
                    # Update incident status based on workflow
                    status = workflow_data.get('status', 'in_progress')
                    updated_incident = await self.db_manager.update_incident_status(
                        incident_id=incident_id,
                        status=status
                    )
                    return {
                        "status": "success",
                        "workflow_id": f"wf_{incident_id}",
                        "incident_status": updated_incident.status
                    }
            return {"status": "error", "message": "Invalid incident ID"}
        except Exception as e:
            logger.error(f"Error triggering workflow: {str(e)}")
            return {"status": "error", "message": str(e)} 