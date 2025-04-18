from typing import Dict, List, Optional
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
from database import DatabaseManager
from models import SeverityLevel
import traceback
import asyncio
import anthropic

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
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
        
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
            'ANTHROPIC_API_KEY',
            'DATABASE_URL'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    async def _generate_claude_prompt(self, title: str, content: str) -> str:
        """Generate a Claude.ai prompt using Heroku AI."""
        try:
            logger.info("Starting Claude.ai prompt generation")
            # Prepare the prompt
            prompt = f"""Based on the following security knowledge:

Title: {title}
Content: {content}

Please provide:
1. A detailed analysis of the security implications
2. Specific indicators to look for in logs and monitoring systems
3. Recommended investigation steps
4. Potential mitigation strategies
5. Relevant security controls to implement

Format your response in clear sections with bullet points where appropriate."""
            
            logger.info("Sending prompt to Heroku AI")
            # Query the model
            response = self.heroku_ai.query_model(prompt)
            logger.info(f"Received response from Heroku AI: {response}")
            
            if not response:
                logger.error("No response received from Heroku AI")
                return "Error generating analysis"
                
            result = response.get("response", "Error generating response")
            if not result or result == "Error generating response":
                logger.error("Invalid response format from Heroku AI")
                return "Error generating analysis"
                
            logger.info("Successfully generated Claude.ai prompt")
            return result
        except Exception as e:
            logger.error(f"Error generating Claude prompt: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return "Error generating analysis"
    
    def _generate_guidance_prompt(self, title: str, content: str) -> str:
        """Generate a specific guidance prompt based on the knowledge article."""
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

        return f"""You are an expert security incident advisor responding to a potential {incident_type} incident. 

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

    def _get_claude_guidance(self, title: str, content: str) -> str:
        """Get guidance from Claude for a specific knowledge article."""
        try:
            logger.info("Generating guidance prompt...")
            prompt = self._generate_guidance_prompt(title, content)
            
            logger.info("Creating Anthropic client...")
            client = anthropic.Client(self.anthropic_api_key)
            
            logger.info("Sending request to Claude...")
            response = client.completion(
                prompt=f"{anthropic.HUMAN_PROMPT} {prompt}{anthropic.AI_PROMPT}",
                model="claude-3-7-sonnet-20250219",
                max_tokens_to_sample=4096,
                temperature=0,
            )
            
            logger.info("Received response from Claude")
            return response.completion
            
        except Exception as e:
            logger.error(f"Error getting Claude guidance: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return f"Error: {str(e)}"

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
                
                formatted_results = []
                for r in results:
                    # Get guidance from Claude for this knowledge article
                    guidance = asyncio.run(self._get_claude_guidance(r.title, r.content))
                    
                    formatted_results.append({
                        "title": r.title,
                        "content": r.content,
                        "guidance": guidance
                    })
                
                return {
                    "status": "success",
                    "message": "🔍 Security Knowledge Search Results",
                    "results": formatted_results
                }
            elif command_text.startswith('incident'):
                # Parse incident creation command
                parts = command_text[9:].strip().split('|')
                if len(parts) >= 3:
                    title = parts[0].strip()
                    description = parts[1].strip()
                    severity = SeverityLevel(parts[2].strip().lower())
                    
                    incident = self.db_manager.create_incident(
                        title=title,
                        description=description,
                        severity=severity
                    )
                    
                    return {
                        "status": "success",
                        "message": "🚨 Incident created",
                        "incident_id": incident.id
                    }
            elif 'charlotte' in command_text:
                # Handle Charlotte queries
                query = command_text.replace('charlotte', '').strip()
                logger.info(f"Charlotte query extracted: '{query}'")
                results = self.db_manager.search_knowledge(query)
                logger.info(f"Charlotte search returned {len(results)} results")
                
                if not results:
                    return {
                        "status": "success",
                        "message": "No relevant knowledge found for your query."
                    }
                
                # Get the first most relevant result
                result = results[0]
                analysis = asyncio.run(self._generate_claude_prompt(result.title, result.content))
                
                return {
                    "status": "success",
                    "message": "🤖 Charlotte's Analysis",
                    "results": [{
                        "title": result.title,
                        "content": result.content,
                        "analysis": analysis
                    }]
                }
            
            # If no specific command is found, treat it as a search query
            logger.info(f"Treating command as search query: '{command_text}'")
            results = self.db_manager.search_knowledge(command_text)
            logger.info(f"Fallback search returned {len(results)} results")
            
            formatted_results = []
            for r in results:
                guidance_prompt = f"""Based on this {r.title.lower()} knowledge:
1. What specific indicators should I look for?
2. Which logs or data sources should I analyze?
3. What tools or commands would be most helpful?
4. What are the potential impact scenarios?
5. What mitigation steps should I consider?"""
                
                formatted_results.append({
                    "title": r.title,
                    "content": r.content,
                    "guidance_prompt": guidance_prompt
                })
            
            return {
                "status": "success",
                "message": "🔍 Security Knowledge Search Results",
                "results": formatted_results
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