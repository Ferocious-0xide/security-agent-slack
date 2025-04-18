import os
import requests
from typing import List, Dict, Any
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)  # Set to DEBUG level
logger = logging.getLogger(__name__)

class InferenceClient:
    def __init__(self, cohere_key: str = None, anthropic_key: str = None):
        load_dotenv()
        self.cohere_key = cohere_key or os.getenv("EMBEDDING_KEY")
        self.anthropic_key = anthropic_key or os.getenv("ANTHROPIC_API_KEY")
        
        if not self.cohere_key:
            raise ValueError("Cohere API key is required")
        
        # Cohere configuration
        self.cohere_url = os.getenv("EMBEDDING_URL", "https://api.cohere.ai/v1")
        self.cohere_model_id = os.getenv("EMBEDDING_MODEL_ID", "embed-english-v3.0")
        self.cohere_headers = {
            "Authorization": f"Bearer {self.cohere_key}",
            "Content-Type": "application/json"
        }
        
        # Anthropic configuration
        if self.anthropic_key:
            self.anthropic_url = "https://api.anthropic.com/v1"
            self.anthropic_headers = {
                "x-api-key": self.anthropic_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }

    def embeddings_create(self, model: str, texts: List[str]) -> List[List[float]]:
        """Create embeddings using Cohere."""
        try:
            logger.debug(f"Making request to {self.cohere_url}/v1/embeddings")
            logger.debug(f"Headers: {self.cohere_headers}")
            logger.debug(f"Request body: {{'model': {self.cohere_model_id}, 'input': {texts}, 'input_type': 'search_document'}}")
            
            response = requests.post(
                f"{self.cohere_url}/v1/embeddings",
                headers=self.cohere_headers,
                json={
                    "model": self.cohere_model_id,
                    "input": texts,
                    "input_type": "search_document"
                }
            )
            response.raise_for_status()
            
            response_json = response.json()
            logger.debug(f"Response: {response_json}")
            
            embeddings = response_json["data"]
            logger.debug(f"Number of embeddings: {len(embeddings)}")
            logger.debug(f"First embedding dimensions: {len(embeddings[0]['embedding'])}")
            
            result = [e["embedding"] for e in embeddings]
            logger.debug(f"Returning {len(result)} embeddings")
            return result
        except Exception as e:
            logger.error(f"Error creating embeddings: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.content}")
            raise

    def chat_completion(self, messages: List[Dict[str, str]], model: str = "claude-3-sonnet-20240229") -> str:
        """Generate chat completion using Anthropic."""
        if not self.anthropic_key:
            raise ValueError("Anthropic API key is required for chat completions")
            
        try:
            response = requests.post(
                f"{self.anthropic_url}/messages",
                headers=self.anthropic_headers,
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 1024
                }
            )
            response.raise_for_status()
            return response.json()["content"][0]["text"]
        except Exception as e:
            logger.error(f"Error generating chat completion: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.content}")
            raise 