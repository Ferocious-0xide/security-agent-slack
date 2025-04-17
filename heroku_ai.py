import os
import json
import logging
import requests
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class HerokuAI:
    def __init__(self, app_name: str):
        self.app_name = app_name
        self.inference_url = os.getenv('INFERENCE_URL')
        self.inference_key = os.getenv('INFERENCE_KEY')
        self.model_id = os.getenv('INFERENCE_MODEL_ID')
        
        if not all([self.inference_url, self.inference_key, self.model_id]):
            raise EnvironmentError("Missing required environment variables for Heroku AI")
        
        self.headers = {
            "Authorization": f"Bearer {self.inference_key}",
            "Content-Type": "application/json"
        }
    
    def query_model(self, prompt: str, options: Optional[Dict] = None) -> Dict:
        """Query the AI model with a prompt and optional parameters."""
        try:
            endpoint_url = f"{self.inference_url}/v1/chat/completions"
            
            payload = {
                "model": self.model_id,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 1000,
                "stream": False
            }
            
            if options:
                payload.update(options)
            
            response = requests.post(
                endpoint_url,
                headers=self.headers,
                json=payload
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "response": result["choices"][0]["message"]["content"]
                }
            else:
                logger.error(f"API request failed: {response.status_code}, {response.text}")
                raise Exception(f"API request failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error querying model: {str(e)}")
            raise 