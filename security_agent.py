from typing import Dict, List, Optional
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
from database import DatabaseManager
from models import SeverityLevel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SecurityAgent:
    def __init__(self):
        load_dotenv()
        self.slack_bot_token = os.getenv('SLACK_BOT_TOKEN')
        self.slack_app_token = os.getenv('SLACK_APP_TOKEN')
        self.slack_signing_secret = os.getenv('SLACK_SIGNING_SECRET')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        
        # Initialize components
        self._validate_environment()
        self.db_manager = DatabaseManager()
        
    def _validate_environment(self) -> None:
        """Validate that all required environment variables are set."""
        required_vars = [
            'SLACK_BOT_TOKEN',
            'SLACK_APP_TOKEN',
            'SLACK_SIGNING_SECRET',
            'OPENAI_API_KEY',
            'DATABASE_URL'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    async def process_slack_command(self, command: Dict) -> Dict:
        """Process incoming Slack commands."""
        try:
            logger.info(f"Processing Slack command: {command}")
            command_text = command.get('text', '').lower()
            
            if command_text.startswith('search'):
                query = command_text[7:].strip()
                results = await self.db_manager.search_knowledge(query)
                return {
                    "status": "success",
                    "message": "Search results",
                    "results": [{"title": r.title, "content": r.content} for r in results]
                }
            elif command_text.startswith('incident'):
                # Parse incident creation command
                parts = command_text[9:].strip().split('|')
                if len(parts) >= 3:
                    title = parts[0].strip()
                    description = parts[1].strip()
                    severity = SeverityLevel(parts[2].strip().lower())
                    
                    incident = await self.db_manager.create_incident(
                        title=title,
                        description=description,
                        severity=severity
                    )
                    
                    return {
                        "status": "success",
                        "message": "Incident created",
                        "incident_id": incident.id
                    }
            
            return {"status": "error", "message": "Unknown command"}
        except Exception as e:
            logger.error(f"Error processing Slack command: {str(e)}")
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