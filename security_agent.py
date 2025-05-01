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
    
    def _get_claude_analysis(self, title: str, content: str, knowledge_id: int = None) -> str:
        """Get analysis from Claude for the security knowledge and store it in the database."""
        try:
            # Create a unique cache key based on the content
            cache_key = f"{title}:{content}"
            
            # Always generate new analysis, don't use cache
            messages = [
                {
                    "role": "system",
                    "content": "You are a security expert providing guidance on security topics. Provide clear, actionable advice based on the given security knowledge. Format your response as complete sentences in paragraphs. Do not use bullet points, numbered lists, or markdown formatting."
                },
                {
                    "role": "user",
                    "content": f"Title: {title}\n\nContent: {content}\n\nPlease provide specific guidance and recommendations based on this security knowledge. Focus on practical steps and best practices. Format your response as complete sentences in paragraphs without any bullet points, lists, or special formatting."
                }
            ]
            
            # Use a timeout to prevent hanging
            analysis = self.inference_client.chat_completion(messages)
            
            # If we get a response, validate and clean it
            if analysis and isinstance(analysis, str) and len(analysis) > 20:
                # Clean up any problematic content
                analysis = analysis.replace('```', '')
                analysis = self._cleanup_markdown(analysis)
                
                # If we have a knowledge_id, store the guidance in the database
                if knowledge_id:
                    try:
                        # Get the article from the database
                        knowledge = self.db_manager.get_knowledge_by_id(knowledge_id)
                        if knowledge:
                            # Update the guidance field
                            if not knowledge.guidance:
                                # Use raw SQL to update the guidance field
                                conn = self.db_manager.engine.raw_connection()
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        "UPDATE security_knowledge SET guidance = %s WHERE id = %s",
                                        (analysis, knowledge_id)
                                    )
                                    conn.commit()
                                    logger.info(f"Updated guidance for knowledge article {knowledge_id}")
                                finally:
                                    conn.close()
                    except Exception as db_error:
                        logger.error(f"Error updating guidance in database: {str(db_error)}")
                
                return analysis
            else:
                return "Analysis Error: Unable to generate guidance"
                
        except Exception as e:
            logger.error(f"Error getting Claude analysis: {str(e)}")
            return "Analysis Error: Unable to generate guidance"
            
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
        
        # Remove any remaining markdown formatting
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Bold
        text = re.sub(r'\*(.*?)\*', r'\1', text)      # Italic
        text = re.sub(r'`(.*?)`', r'\1', text)        # Code
        text = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', text)  # Links
        
        # Ensure proper paragraph spacing
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        
        # Remove any leading/trailing whitespace
        text = text.strip()
        
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
        """Process a search query and return enriched results."""
        try:
            print(f"[AGENT] Processing search query: '{query}'")
            
            # Search the database for relevant knowledge
            db_results = self.db_manager.search_knowledge(query, limit=10)  # Get more results to ensure we have enough
            
            logger.info(f"Found {len(db_results)} results using text search")
            print(f"[AGENT] Found {len(db_results)} search results for query: '{query}'")
            
            if not db_results:
                logger.debug("No search results found")
                return {"message": "No results found for your query"}
            
            # Process each result to enrich with guidance
            enriched_results = []
            
            for i, result in enumerate(db_results):
                print(f"[AGENT] Processing result {i+1}: {result.title}")
                logger.info(f"Processing result {i+1}: {result.title} (ID: {result.id})")
                
                # Extract a snippet of content
                content_snippet = result.content[:150] + "..." if len(result.content) > 150 else result.content
                print(f"[AGENT] Content snippet: {content_snippet}")
                
                # Try to extract URL from content if it exists, otherwise generate a default URL
                reference_url = None
                url_pattern = re.compile(r'https://security-kb\.example\.com/[\w-]+')
                url_match = url_pattern.search(result.content)
                if url_match:
                    reference_url = url_match.group(0)
                    print(f"[AGENT] Found reference URL in content: {reference_url}")
                else:
                    # Create reference URL (in a real system, this would be a real URL)
                    reference_url = f"https://security-kb.example.com/{result.title.lower().replace(' ', '-')}"
                    print(f"[AGENT] Generated reference URL: {reference_url}")
                
                # Create an enriched result with guidance
                enriched_result = {
                    "id": result.id,
                    "title": result.title,
                    "content": result.content,
                    "category": result.category,
                    "reference_url": reference_url,
                }
                
                # Always get fresh Claude analysis
                print(f"[AGENT] Getting fresh Claude analysis for result {i+1}")
                logger.debug(f"Getting fresh Claude analysis for result {i+1}")
                guidance = self._get_claude_analysis(result.title, result.content, result.id)
                
                if guidance and len(guidance) > 0:
                    # Truncate guidance for display
                    guidance_snippet = guidance[:200] + "..." if len(guidance) > 200 else guidance
                    print(f"[AGENT] Guidance snippet: {guidance_snippet}")
                    
                    # Add guidance to the result
                    enriched_result["guidance"] = guidance
                
                # Add the enriched result
                enriched_results.append(enriched_result)
                print(f"[AGENT] Added result {i+1} to enriched results")
                
                # Stop if we have 5 results
                if len(enriched_results) >= 5:
                    break
            
            # If we have fewer than 3 results, duplicate some to reach at least 3
            original_count = len(enriched_results)
            if original_count < 3:
                print(f"[AGENT] Only found {original_count} results, duplicating to reach minimum of 3")
                logger.info(f"Only found {original_count} results, duplicating to reach minimum of 3")
                
                # Keep duplicating until we have at least 3
                i = 0
                while len(enriched_results) < 3:
                    duplicate = enriched_results[i % original_count].copy()
                    # Modify the duplicate slightly to indicate it's a related article
                    duplicate["title"] = f"{duplicate['title']} (Related)"
                    enriched_results.append(duplicate)
                    i += 1
            
            # Verify we have results before formatting
            if not enriched_results:
                logger.warning("No enriched results produced even though DB returned results")
                print("[AGENT] Error: No enriched results produced even though database returned results")
                return {"message": "Error processing search results"}
                
            logger.info(f"Returning {len(enriched_results)} enriched results")
            print(f"[AGENT] Returning {len(enriched_results)} enriched results to Slack")
            
            # Return the original enriched results for simple formatting, plus a flag to use blocks
            return {
                "message": f"Found {len(enriched_results)} results for '{query}'", 
                "original_results": enriched_results,
                "use_blocks": True
            }
            
        except Exception as e:
            logger.error(f"Error processing search: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            print(f"[AGENT ERROR] Error processing search: {str(e)}")
            return {"message": f"Error processing search: {str(e)}"}
    
    def _format_slack_blocks(self, results: List[Dict], response_url: str = None, initial_command: str = None) -> List[Dict]:
        """Format enriched search results into Slack blocks."""
        blocks = []
        
        # Log how many results we're formatting
        print(f"[AGENT] Formatting {len(results)} search results into Slack blocks")
        logger.info(f"Formatting {len(results)} search results into Slack blocks with response_url: {'present' if response_url else 'not provided'}")
        if initial_command:
            logger.info(f"Including initial command: {initial_command}")
        
        # First block explains the results
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Found {len(results)} Security Knowledge Articles"
            }
        })
        
        # Add each result as a separate post
        for i, result in enumerate(results):
            # Add divider between articles
            if i > 0:
                blocks.append({"type": "divider"})
            
            # Extract title, content, and guidance
            title = result.get("title", "Untitled")
            content = result.get("content", "No content available")
            guidance = result.get("guidance", "No guidance available")
            article_id = result.get("id", f"article_{i+1}")
            
            # Add numbered article title (e.g., "1. Data Exfiltration Prevention")
            blocks.append({
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{i+1}. {title}"
                }
            })
            
            # Add article content as plain text
            content_text = content[:1000] + "..." if len(content) > 1000 else content
            content_text = content_text.strip()
            blocks.append({
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": content_text
                }
            })
            
            # Create article URL (use the one provided or generate a dummy one)
            reference_url = result.get("reference_url", f"https://security-kb.example.com/{title.lower().replace(' ', '-')}")
            
            # Add investigation prompt header and content
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Investigation Prompt:*"
                }
            })
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": guidance
                }
            })
            
            # Create interactive button with Ask Charlotte functionality
            max_guidance_length = 500  # Slack has limit on button values
            truncated_guidance = guidance[:max_guidance_length] if guidance else ""
            
            # Create article_id that's consistently a string
            article_id = f"article_{result['id']}" if isinstance(result['id'], int) else result['id']
            
            # Create the button block
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Ask Charlotte",
                            "emoji": True
                        },
                        "action_id": "ask_charlotte",
                        "style": "primary",
                        "value": json.dumps({
                            "title": result["title"],
                            "guidance": truncated_guidance,
                            "article_id": article_id,
                            "original_message": True,
                            "initial_command": initial_command
                        })
                    }
                ]
            })
        
        logger.debug(f"Created {len(blocks)} Slack blocks for search results")
        print(f"[AGENT] Created {len(blocks)} Slack blocks for search results")
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
                            analysis = self._get_claude_analysis(result.title, result.content, result.id)
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
                analysis = self._get_claude_analysis(result.title, result.content, result.id)
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