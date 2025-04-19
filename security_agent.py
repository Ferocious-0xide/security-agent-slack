from typing import Dict, List, Optional, Any
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
from database import DatabaseManager
from models import SeverityLevel
import traceback
import requests
import json
from heroku_inference import InferenceClient

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SecurityAgent:
    def __init__(self):
        load_dotenv()
        self.slack_app_token = os.getenv('SLACK_APP_TOKEN')
        self.slack_signing_secret = os.getenv('SLACK_SIGNING_SECRET')
        self.anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        
        # Initialize components
        self._validate_environment()
        self.db_manager = DatabaseManager()
        self.inference_client = InferenceClient()
        
    def _validate_environment(self) -> None:
        """Validate that all required environment variables are set."""
        required_vars = [
            'SLACK_APP_TOKEN',
            'SLACK_SIGNING_SECRET',
            'DATABASE_URL',
            'EMBEDDING_URL',
            'EMBEDDING_KEY',
            'EMBEDDING_MODEL_ID',
            'INFERENCE_URL',
            'INFERENCE_KEY',
            'INFERENCE_MODEL_ID'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    def _get_claude_analysis(self, title: str, content: str) -> str:
        """Get analysis from Claude for the security knowledge."""
        try:
            # Determine incident type based on title
            incident_type = "security incident"
            if any(keyword in title.lower() for keyword in ["data", "exfiltration"]):
                incident_type = "data exfiltration incident"
            elif any(keyword in title.lower() for keyword in ["privilege", "escalation"]):
                incident_type = "privilege escalation incident"
            elif "ransomware" in title.lower():
                incident_type = "ransomware incident"
            elif any(keyword in title.lower() for keyword in ["lateral", "movement"]):
                incident_type = "lateral movement incident"
            elif "network" in title.lower():
                incident_type = "network security incident"

            messages = [
                {
                    "role": "user",
                    "content": f"""As a security analyst, I need your guidance on a {incident_type}. Here's the context from our security knowledge base:

Title: {title}
Content: {content}

Based on this information and your expertise in cybersecurity:
1. What is your assessment of this security issue?
2. What investigation angles should we pursue?
3. What artifacts should we collect and analyze?
4. What containment measures do you recommend?
5. How might this connect to larger attack patterns?

Please provide a concise but thorough analysis."""
                }
            ]

            analysis = self.inference_client.chat_completion(messages)
            return analysis

        except Exception as e:
            logger.error(f"Error getting Claude analysis: {str(e)}")
            return "Error: Unable to generate security analysis."

    def process_command(self, command_text: str) -> Dict[str, Any]:
        """Process a security command and return the response."""
        try:
            if not command_text:
                return {"message": "Please specify a command. Available commands: search, help"}
                
            parts = command_text.split()
            command = parts[0].lower()
            
            if command == "search":
                if len(parts) < 2:
                    return {"message": "Please provide a search query"}
                query = " ".join(parts[1:])
                return self._process_search(query)
            elif command == "help":
                return {"message": "Available commands:\n- search <query>: Search security knowledge base\n- help: Show this help message"}
            else:
                return {"message": f"Unknown command: {command}. Type 'help' for available commands"}
                
        except Exception as e:
            self.logger.error(f"Error processing command: {str(e)}")
            return {"message": f"Error processing command: {str(e)}"}
            
    def _process_search(self, query: str) -> Dict[str, Any]:
        """Process a search query and return formatted results."""
        try:
            # Get search results
            results = self.db_manager.search_knowledge(query)
            if not results:
                return {"message": "No results found for your query"}
                
            # Format results with blocks
            blocks = []
            for result in results:
                # Add knowledge article
                blocks.extend([
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": result.title
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": result.content
                        }
                    },
                    {
                        "type": "divider"
                    }
                ])
                
                # Add Claude analysis
                analysis = self._get_claude_analysis(result.title, result.content)
                if analysis:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Claude.ai Prompt:*\n{analysis}"
                        }
                    })
                    blocks.append({"type": "divider"})
                    
            return {"blocks": blocks}
            
        except Exception as e:
            logger.error(f"Error processing search: {str(e)}")
            return {"message": f"Error processing search: {str(e)}"}
    
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