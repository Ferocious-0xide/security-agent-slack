import os
import requests
import time
from typing import List, Dict, Any, Optional
import logging
from dotenv import load_dotenv
import json
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InferenceClient:
    def __init__(self, cohere_key: str = None, inference_key: str = None):
        load_dotenv()
        self.cohere_key = cohere_key or os.getenv("EMBEDDING_KEY")
        self.inference_key = inference_key or os.getenv("INFERENCE_KEY")
        
        if not self.cohere_key:
            raise ValueError("Cohere API key is required")
        
        # Cohere configuration
        self.cohere_url = os.getenv("EMBEDDING_URL", "https://us.inference.heroku.com")
        self.cohere_model_id = os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual")
        self.cohere_headers = {
            "Authorization": f"Bearer {self.cohere_key}",
            "Content-Type": "application/json"
        }
        
        # Inference configuration
        if self.inference_key:
            self.inference_url = os.getenv("INFERENCE_URL", "https://us.inference.heroku.com")
            self.inference_model_id = os.getenv("INFERENCE_MODEL_ID", "claude-3-7-sonnet")
            self.inference_headers = {
                "Authorization": f"Bearer {self.inference_key}",
                "Content-Type": "application/json"
            }
        
        # Set retry configuration
        self.max_retries = 3
        self.retry_delay = 1  # seconds

    def embeddings_create(self, model: str, texts: List[str]) -> Optional[List[List[float]]]:
        """
        Create embeddings using Cohere with retry logic.
        Returns embeddings or None if failed after retries.
        """
        if not texts:
            logger.warning("Empty texts provided to embeddings_create")
            return []
            
        # Ensure texts are strings and not too long
        processed_texts = []
        for text in texts:
            if not isinstance(text, str):
                text = str(text)
            # Limit text length to prevent request size issues
            if len(text) > 8000:
                text = text[:8000]
            processed_texts.append(text)
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Making embeddings request (attempt {attempt+1}/{self.max_retries})")
                
                response = requests.post(
                    f"{self.cohere_url}/v1/embeddings",
                    headers=self.cohere_headers,
                    json={
                        "model": self.cohere_model_id,
                        "input": processed_texts,
                        "input_type": "search_document"
                    },
                    timeout=30  # Set a timeout
                )
                response.raise_for_status()
                
                response_json = response.json()
                embeddings = response_json.get("data", [])
                
                if not embeddings:
                    logger.warning(f"Empty embeddings returned: {response_json}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (attempt + 1))
                        continue
                    return []
                
                result = [e.get("embedding", []) for e in embeddings]
                logger.info(f"Successfully created {len(result)} embeddings")
                return result
                
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout creating embeddings (attempt {attempt+1})")
            except requests.exceptions.RequestException as e:
                logger.error(f"Error creating embeddings (attempt {attempt+1}): {str(e)}")
                if hasattr(e, 'response') and e.response:
                    logger.error(f"Response status: {e.response.status_code}")
                    logger.error(f"Response content: {e.response.text[:500]}")
            except Exception as e:
                logger.error(f"Unexpected error creating embeddings: {str(e)}")
                logger.error(traceback.format_exc())
            
            # Retry with exponential backoff
            if attempt < self.max_retries - 1:
                sleep_time = self.retry_delay * (2 ** attempt)
                logger.info(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
        
        logger.error("Failed to create embeddings after all retries")
        return None

    def chat_completion(self, messages: List[Dict[str, str]]) -> str:
        """
        Send a chat completion request to the inference API with retry logic.
        Returns the response content or a fallback message.
        """
        if not self.inference_key:
            logger.error("No inference API key configured")
            return self._get_fallback_response(messages)
            
        if not messages:
            logger.warning("Empty messages provided to chat_completion")
            return "No messages provided for chat completion"
        
        for attempt in range(self.max_retries):
            try:
                # Prepare the request
                url = f"{self.inference_url}/v1/chat/completions"
                payload = {
                    "model": self.inference_model_id,
                    "messages": messages,
                    "stream": False,
                    "temperature": 0.7,
                    "max_tokens": 2048
                }
                
                # Log the request (only for the first attempt to avoid log spam)
                if attempt == 0:
                    logger.info(f"Making chat completion request with {len(messages)} messages")
                
                # Make the request with timeout
                response = requests.post(
                    url,
                    headers=self.inference_headers,
                    json=payload,
                    timeout=45  # Increased timeout for chat completions
                )
                
                # Handle different response statuses
                if response.status_code == 200:
                    response_json = response.json()
                    
                    # Extract the response content
                    if 'choices' in response_json and len(response_json['choices']) > 0:
                        content = response_json['choices'][0]['message']['content']
                        logger.info(f"Chat completion successful ({len(content)} chars)")
                        return content
                    else:
                        logger.warning(f"No choices in chat completion response")
                        if attempt < self.max_retries - 1:
                            time.sleep(self.retry_delay * (attempt + 1))
                            continue
                elif response.status_code == 429:
                    # Rate limit - wait longer before retry
                    logger.warning(f"Rate limited in chat completion (attempt {attempt+1})")
                    if attempt < self.max_retries - 1:
                        sleep_time = self.retry_delay * (2 ** (attempt + 2))  # Longer backoff for rate limits
                        logger.info(f"Rate limited, retrying in {sleep_time} seconds...")
                        time.sleep(sleep_time)
                        continue
                else:
                    logger.error(f"Error in chat completion: {response.status_code}")
                    logger.error(f"Response: {response.text[:500]}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout in chat completion (attempt {attempt+1})")
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error in chat completion (attempt {attempt+1}): {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error in chat completion: {str(e)}")
                logger.error(traceback.format_exc())
            
            # Retry with exponential backoff
            if attempt < self.max_retries - 1:
                sleep_time = self.retry_delay * (2 ** attempt)
                logger.info(f"Retrying chat completion in {sleep_time} seconds...")
                time.sleep(sleep_time)
        
        # Use fallback response after all retries
        logger.warning("Using fallback response after failed chat completion")
        return self._get_fallback_response(messages)
    
    def _get_fallback_response(self, messages: List[Dict[str, str]]) -> str:
        """Generate a fallback response when API requests fail."""
        try:
            # Try to extract context from messages
            query = ""
            for message in reversed(messages):
                if message.get("role") == "user":
                    query = message.get("content", "")
                    break
            
            if "incident" in query.lower():
                return """
Based on available information, this appears to be a security incident requiring investigation.
Focus on collecting logs, isolating affected systems, and preserving evidence.
Contact your security team immediately for assistance with the investigation.
                """.strip()
            elif "search" in query.lower() or "find" in query.lower():
                return """
I couldn't access the knowledge base at this time. Please try your search again later,
or contact your security team directly if this is an urgent matter.
                """.strip()
            else:
                return """
I'm currently experiencing connection issues. Please try again in a few moments,
or reach out to your security team directly if you need immediate assistance.
                """.strip()
        except Exception:
            # Ultimate fallback if everything else fails
            return "I'm having trouble connecting to the knowledge base. Please try again later." 