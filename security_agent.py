from typing import Dict, List, Optional
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
from database import DatabaseManager
from models import SeverityLevel
import asyncio

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
        self.db = DatabaseManager()
        self.command_handlers = {
            "search": self._handle_search,
            "incident": self._handle_incident,
            "charlotte": self._handle_charlotte
        }
        
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
    
    async def process_slack_command(self, command: str, text: str) -> Dict:
        """Process a Slack command and return the response."""
        try:
            # Split the command text into parts
            parts = text.strip().split(maxsplit=1)
            if not parts:
                return {"error": "No command provided"}
            
            subcommand = parts[0].lower()
            query = parts[1] if len(parts) > 1 else ""
            
            # Handle different command formats
            if subcommand in self.command_handlers:
                return await self.command_handlers[subcommand](query)
            else:
                # Default behavior: search knowledge base
                return await self._handle_search(text)
        except Exception as e:
            logger.error(f"Error processing command: {str(e)}")
            return {"error": f"Error processing command: {str(e)}"}
    
    async def _handle_search(self, query: str) -> Dict:
        """Handle search command."""
        try:
            results = await self.db.search_knowledge(query)
            if not results:
                return {"error": "No results found"}
            return {
                "success": True,
                "results": [{"title": r.title, "content": r.content} for r in results]
            }
        except Exception as e:
            logger.error(f"Error in search: {str(e)}")
            return {"error": f"Error in search: {str(e)}"}
    
    async def _handle_incident(self, text: str) -> Dict:
        """Handle incident creation command."""
        try:
            # Parse incident details
            parts = text.split("|")
            if len(parts) != 3:
                return {"error": "Invalid format. Use: /security incident <title> | <description> | <severity>"}
            
            title = parts[0].strip()
            description = parts[1].strip()
            severity = parts[2].strip().upper()
            
            # Validate severity
            if severity not in SeverityLevel.__members__:
                return {"error": f"Invalid severity level. Must be one of: {', '.join(SeverityLevel.__members__)}"}
            
            # Create incident
            incident = await self.db.create_incident(
                title=title,
                description=description,
                severity=SeverityLevel[severity]
            )
            
            return {
                "success": True,
                "incident_id": incident.id,
                "message": f"Incident created with ID: {incident.id}"
            }
        except Exception as e:
            logger.error(f"Error creating incident: {str(e)}")
            return {"error": f"Error creating incident: {str(e)}"}
    
    async def _handle_charlotte(self, query: str) -> Dict:
        """Handle Charlotte AI queries."""
        try:
            # For now, just search the knowledge base
            results = await self.db.search_knowledge(query)
            if not results:
                return {"error": "No relevant information found"}
            
            # Format response
            response = "Here's what I found:\n\n"
            for r in results:
                response += f"*{r.title}*\n{r.content}\n\n"
            
            return {
                "success": True,
                "response": response
            }
        except Exception as e:
            logger.error(f"Error in Charlotte query: {str(e)}")
            return {"error": f"Error in Charlotte query: {str(e)}"}
    
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
                    results = await self.db.search_knowledge(message)
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
            results = await self.db.search_knowledge(query)
            return [{"title": r.title, "content": r.content} for r in results]
        except Exception as e:
            logger.error(f"Error querying knowledge base: {str(e)}")
            return []
    
    async def create_incident(self, incident_data: Dict) -> Dict:
        """Create a new security incident."""
        try:
            logger.info(f"Creating incident: {incident_data}")
            incident = await self.db.create_incident(
                title=incident_data['title'],
                description=incident_data['description'],
                severity=SeverityLevel(incident_data['severity'].lower())
            )
            
            # Search for relevant knowledge
            results = await self.db.search_knowledge(incident_data['description'])
            for knowledge in results:
                await self.db.link_knowledge_to_incident(
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
                incident = await self.db.get_incident(incident_id)
                if incident:
                    # Update incident status based on workflow
                    status = workflow_data.get('status', 'in_progress')
                    updated_incident = await self.db.update_incident_status(
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