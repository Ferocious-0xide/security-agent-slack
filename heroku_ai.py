import os
import json
import logging
import aiohttp
from typing import Dict, Optional
import traceback
import asyncio

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
    
    async def query_model(self, prompt: str) -> Dict[str, str]:
        """Query the Heroku Inference API with retry logic."""
        try:
            # Set up retry parameters
            max_retries = 3
            base_delay = 1  # seconds
            
            for attempt in range(max_retries):
                try:
                    # Prepare the request
                    url = f"{self.inference_url}/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {self.inference_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": self.model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": True
                    }
                    
                    # Log the request
                    logger.info(f"Making request to Heroku Inference API: {url}")
                    
                    # Make the request
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, headers=headers, json=payload) as response:
                            if response.status == 200:
                                # Initialize response content
                                full_response = ""
                                current_event = {}
                                
                                # Process the stream
                                async for line in response.content:
                                    line = line.decode('utf-8').strip()
                                    if not line:
                                        continue
                                        
                                    if line.startswith('event:'):
                                        current_event['event'] = line[6:].strip()
                                    elif line.startswith('data:'):
                                        data = line[5:].strip()
                                        if data == '[DONE]':
                                            break
                                        try:
                                            json_data = json.loads(data)
                                            if 'choices' in json_data and len(json_data['choices']) > 0:
                                                if 'delta' in json_data['choices'][0]:
                                                    content = json_data['choices'][0]['delta'].get('content', '')
                                                    full_response += content
                                        except json.JSONDecodeError:
                                            logger.warning(f"Failed to decode JSON data: {data}")
                                            continue
                                
                                return {"response": full_response}
                            elif response.status == 408:  # Request Timeout
                                if attempt < max_retries - 1:
                                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                                    logger.warning(f"Request timed out, retrying in {delay} seconds...")
                                    await asyncio.sleep(delay)
                                    continue
                                else:
                                    logger.error("Max retries reached for timeout")
                                    return {"response": "Error: Request timed out after multiple retries"}
                            else:
                                error_text = await response.text()
                                logger.error(f"Error querying model: {error_text}")
                                return {"response": f"Error: API request failed with status {response.status}"}
                                
                except aiohttp.ClientError as e:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Network error: {str(e)}, retrying in {delay} seconds...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"Max retries reached for network error: {str(e)}")
                        return {"response": f"Error: Network error after multiple retries"}
                    
        except Exception as e:
            logger.error(f"Error in query_model: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"response": f"Error: {str(e)}"} 