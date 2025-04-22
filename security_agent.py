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
import re
import time

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
        
        # Initialize components
        self._validate_environment()
        self.db_manager = DatabaseManager()
        self.inference_client = InferenceClient()
        
        # Cache for Claude analysis to avoid duplicate responses
        self.analysis_cache = {}
        
        # Cache for search results to avoid duplicate processing
        self.search_cache = {}
        
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
        # Create a cache key based on title and content
        cache_key = f"{title}:{content[:100]}"
        
        # Check if we have a cached response
        if cache_key in self.analysis_cache:
            logger.debug(f"Using cached Claude analysis for: {title}")
            return self.analysis_cache[cache_key]
            
        try:
            logger.debug(f"Getting Claude analysis for article: {title}")
            
            # Use a prompt that explicitly forbids all formatting
            prompt = f"""Based on the following security knowledge article, generate a brief investigation guide that a security analyst can follow.

CRITICAL FORMATTING INSTRUCTIONS - DO NOT IGNORE:
1. Write your response as ONE CONTINUOUS PARAGRAPH with no line breaks except between major sections
2. DO NOT use bullet points, numbered lists, or any kind of markdown formatting
3. DO NOT use hash symbols (#), asterisks (*), hyphens (-), or any other special characters for formatting
4. DO NOT include any headers, section titles, or labels within your text
5. Write in a natural, conversational tone as if speaking directly to the security analyst
6. Do not start with "Investigation Guide:" or any other title/header
7. Your response should be fluid prose like a human would write in an email or document

Knowledge article:
Title: {title}
Content: {content}"""

            messages = [{"role": "user", "content": prompt}]

            # Log the request
            logger.debug("Sending request to Claude")
            
            try:
                # Use a timeout to prevent hanging
                analysis = self.inference_client.chat_completion(messages)
                
                # If we get a response, validate and clean it
                if analysis and isinstance(analysis, str) and len(analysis) > 20:
                    # Clean up any problematic content
                    analysis = analysis.replace('```', '')
                    
                    # Cache the response
                    self.analysis_cache[cache_key] = analysis
                    return analysis
                else:
                    logger.warning(f"Received invalid analysis response: {analysis}")
                    return "No guidance available for this security article."
                    
            except Exception as inference_error:
                logger.error(f"Inference API error: {str(inference_error)}")
                return "No guidance available for this security article."

        except Exception as e:
            logger.error(f"Error in Claude analysis: {str(e)}")
            return "No guidance available for this security article."
            
    def _cleanup_markdown(self, text: str) -> str:
        """Clean up any markdown formatting that might be in the text."""
        if not text:
            return ""
            
        # Remove hash symbols at the beginning of lines (markdown headers)
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        
        # Remove asterisks used for bullets
        text = re.sub(r'^\s*\*\s+', '', text, flags=re.MULTILINE)
        
        # Remove numbered list formatting
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        
        # Remove other bullet formats
        text = re.sub(r'^\s*-\s+', '', text, flags=re.MULTILINE)
        
        return text

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
                
                # Check cache for recent identical queries
                cache_key = f"search:{query}"
                if cache_key in self.search_cache:
                    cache_time, cache_result = self.search_cache[cache_key]
                    # Use cached result if less than 5 minutes old
                    if time.time() - cache_time < 300:
                        logger.debug(f"Using cached result for query: {query}")
                        return cache_result
                
                # Process the search
                logger.debug(f"Performing new search for query: {query}")
                result = self._process_search(query)
                
                # Cache the result
                logger.debug(f"Caching search result with keys: {result.keys()}")
                self.search_cache[cache_key] = (time.time(), result)
                
                # Clean up old cache entries
                current_time = time.time()
                self.search_cache = {k: v for k, v in self.search_cache.items() 
                                   if current_time - v[0] < 600}  # Keep for 10 minutes
                
                return result
            elif command == "help":
                return {"message": "Available commands:\n- search <query>: Search security knowledge base\n- help: Show this help message"}
            else:
                return {"message": f"Unknown command: {command}. Type 'help' for available commands"}
                
        except Exception as e:
            logger.error(f"Error processing command: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return {"message": f"Error processing command: {str(e)}"}
            
    def _process_search(self, query: str) -> Dict[str, Any]:
        """Process a search query and return formatted results."""
        try:
            logger.debug(f"Processing search query: {query}")
            
            # Get search results
            db_results = self.db_manager.search_knowledge(query)
            logger.info(f"Found {len(db_results)} search results for query: {query}")
            
            if not db_results:
                logger.debug("No search results found")
                return {"message": "No results found for your query"}
            
            # Format results with guidance from Claude
            enriched_results = []
            for i, result in enumerate(db_results):
                logger.info(f"Processing result {i+1}: {result.title} (ID: {result.id})")
                
                # Create enriched result
                enriched_result = {
                    "title": result.title,
                    "content": result.content,
                    "category": result.category if hasattr(result, "category") else "General"
                }
                
                # Try to get Claude analysis but don't break if it fails
                try:
                    logger.debug(f"Getting Claude analysis for result {i+1}")
                    analysis = self._get_claude_analysis(result.title, result.content)
                    
                    if analysis and len(analysis) > 0:
                        logger.debug(f"Claude analysis received for result {i+1}, length: {len(analysis)}")
                        enriched_result["guidance"] = analysis
                    else:
                        logger.warning(f"No valid Claude analysis received for result {i+1}")
                        # Add a placeholder guidance to maintain consistency
                        enriched_result["guidance"] = "Unable to generate investigation prompt for this security article."
                except Exception as e:
                    logger.error(f"Error getting Claude analysis for result {i+1}: {str(e)}")
                    enriched_result["guidance"] = "Unable to generate investigation prompt for this security article."
                
                enriched_results.append(enriched_result)
            
            # Verify we have results before formatting
            if not enriched_results:
                logger.warning("No enriched results produced even though DB returned results")
                return {"message": "Error processing search results"}
                
            logger.info(f"Returning {len(enriched_results)} enriched results")
            
            # Return the original enriched results for simple formatting
            return {
                "message": f"Found {len(enriched_results)} results for '{query}'", 
                "original_results": enriched_results
            }
            
        except Exception as e:
            logger.error(f"Error processing search: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return {"message": f"Error processing search: {str(e)}"}
    
    def _format_slack_blocks(self, results: List[Dict]) -> List[Dict]:
        """Format enriched search results into Slack blocks."""
        blocks = []
        
        # Log how many results we're formatting
        logger.info(f"Formatting {len(results)} search results into Slack blocks")
        
        # First block explains the results (this will be displayed as intro message by SlackHandler)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Found {len(results)} relevant security knowledge articles:*"
            }
        })
        
        # Add a divider before first article
        blocks.append({"type": "divider"})
        
        for i, result in enumerate(results):
            # Log each result we're processing
            logger.info(f"Formatting result {i+1}: {result['title']}")
            
            # Add knowledge article with title (always make it a header to enable splitting)
            header_block = {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{i+1}. {result['title']}",
                    "emoji": True
                }
            }
            blocks.append(header_block)
            logger.debug(f"Added header block for article {i+1}: {result['title']}")
            
            # Add content block - keep it simple
            content_text = result['content']
            if len(content_text) > 2000:  # Be very conservative with text length
                content_text = content_text[:2000] + "..."
                
            content_block = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": content_text
                }
            }
            blocks.append(content_block)
            
            # Add Claude analysis if present
            if "guidance" in result and result["guidance"]:
                guidance = result["guidance"]
                if len(guidance) > 2000:  # Be very conservative with text length
                    guidance = guidance[:2000] + "..."
                    
                logger.debug(f"Adding guidance for article {i+1} with length {len(guidance)}")
                
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Investigation Prompt:*\n{guidance}"
                    }
                })
                
                # Add "Ask Charlotte" button to get a step-by-step process
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Ask Charlotte for steps",
                                "emoji": True
                            },
                            "style": "primary",
                            "value": json.dumps({
                                "article_id": result.get("id", f"article_{i}"),
                                "title": result["title"],
                                "guidance": guidance
                            }),
                            "action_id": "ask_charlotte"
                        }
                    ]
                })
            else:
                logger.warning(f"No guidance found for article {i+1}: {result['title']}")
            
            # Add a divider between articles
            if i < len(results) - 1:
                blocks.append({"type": "divider"})
        
        logger.info(f"Formatted results into {len(blocks)} Slack blocks with {len(results)} articles")
        return blocks
    
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
                    results = self.db_manager.search_knowledge(message)
                    if results:
                        # Enrich results with Claude analysis
                        enriched_results = []
                        for result in results:
                            enriched_result = {
                                "title": result.title,
                                "content": result.content
                            }
                            
                            # Get Claude analysis
                            analysis = self._get_claude_analysis(result.title, result.content)
                            if analysis and not analysis.startswith("Analysis Error"):
                                enriched_result["guidance"] = analysis
                            
                            enriched_results.append(enriched_result)
                            
                        return {
                            "status": "success",
                            "message": "Found relevant security information",
                            "results": enriched_results
                        }
            
            return {"status": "success", "message": "Event processed"}
        except Exception as e:
            logger.error(f"Error processing Slack event: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return {"status": "error", "message": str(e)}
    
    async def query_knowledge_base(self, query: str) -> List[Dict]:
        """Query the security knowledge base."""
        try:
            logger.info(f"Querying knowledge base: {query}")
            results = self.db_manager.search_knowledge(query)
            
            # Enrich results with Claude analysis
            enriched_results = []
            for result in results:
                enriched_result = {
                    "title": result.title,
                    "content": result.content
                }
                
                # Get Claude analysis
                analysis = self._get_claude_analysis(result.title, result.content)
                if analysis and not analysis.startswith("Analysis Error"):
                    enriched_result["guidance"] = analysis
                
                enriched_results.append(enriched_result)
                
            return enriched_results
        except Exception as e:
            logger.error(f"Error querying knowledge base: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return []
    
    async def create_incident(self, incident_data: Dict) -> Dict:
        """Create a new security incident."""
        try:
            logger.info(f"Creating incident: {incident_data}")
            incident = self.db_manager.create_incident(
                title=incident_data['title'],
                description=incident_data['description'],
                severity=SeverityLevel(incident_data['severity'].lower())
            )
            
            # Search for relevant knowledge
            results = self.db_manager.search_knowledge(incident_data['description'])
            for knowledge in results:
                self.db_manager.link_knowledge_to_incident(
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
                incident = self.db_manager.get_incident(incident_id)
                if incident:
                    # Update incident status based on workflow
                    status = workflow_data.get('status', 'in_progress')
                    updated_incident = self.db_manager.update_incident_status(
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
    
    async def process_message(self, text: str, user_id: str = None, channel_id: str = None) -> Dict[str, Any]:
        """Process a message from a user and return a response."""
        logger.info(f"Processing message from user {user_id} in channel {channel_id}: {text}")
        
        try:
            # Process the command using the existing functionality
            result = self.process_command(text)
            
            # Return the result directly
            return result
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return {"message": f"Error processing your request: {str(e)}"} 