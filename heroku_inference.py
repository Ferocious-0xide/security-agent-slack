import os
import requests
from typing import List, Dict, Any
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)  # Set to DEBUG level
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

    def chat_completion(self, messages: List[Dict[str, str]], model: str = None) -> str:
        """Generate chat completion using Heroku Inference."""
        if not self.inference_key:
            raise ValueError("Inference API key is required")
            
        try:
            # Convert messages to system and user messages format
            formatted_messages = []
            for msg in messages:
                formatted_messages.append({
                    "role": "user" if msg["role"] == "user" else "assistant",
                    "content": msg["content"]
                })

            response = requests.post(
                f"{self.inference_url}/v1/chat/completions",
                headers=self.inference_headers,
                json={
                    "model": model or self.inference_model_id,
                    "messages": formatted_messages,
                    "max_tokens": 1024,
                    "temperature": 0.7
                }
            )
            response.raise_for_status()
            
            logger.debug(f"Inference API Response: {response.json()}")
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Error generating chat completion: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.content}")
            raise 