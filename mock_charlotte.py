import os
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import openai
from datetime import datetime
import logging
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import numpy as np
from pgvector.psycopg2 import register_vector
import traceback
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Debug environment variables
logger.info("Checking environment variables...")
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    logger.error("OPENAI_API_KEY not found in environment variables")
    logger.info("Current environment variables:")
    for key in ["OPENAI_API_KEY", "DATABASE_URL", "CHARLOTTE_SERVICE_KEY"]:
        logger.info(f"{key}: {'Set' if os.getenv(key) else 'Not set'}")
    raise ValueError("OPENAI_API_KEY must be set in environment variables")

# Initialize OpenAI client
openai_client = openai.OpenAI(api_key=api_key)
logger.info("OpenAI client initialized successfully")

# Initialize FastAPI app
app = FastAPI(title="Mock Charlotte RAG Service")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
def get_db_connection():
    try:
        conn = psycopg2.connect(
            os.getenv("DATABASE_URL"),
            cursor_factory=RealDictCursor
        )
        register_vector(conn)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

# Models
class Query(BaseModel):
    query: str = Field(..., description="The query to process")
    max_tokens: Optional[int] = Field(500, description="Maximum tokens for response")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context for the query")

class Response(BaseModel):
    answer: str = Field(..., description="The generated answer")
    confidence: float = Field(..., description="Confidence score of the answer")
    sources: List[Dict[str, Any]] = Field(..., description="List of sources used")
    timestamp: str = Field(..., description="Timestamp of the response")

class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message")
    details: Optional[str] = Field(None, description="Additional error details")
    timestamp: str = Field(..., description="Timestamp of the error")

# Helper functions
def get_embedding(text: str) -> List[float]:
    """Get embedding for text using OpenAI."""
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding generation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate embedding")

def format_slack_response(response: Response) -> Dict[str, Any]:
    """Format response for Slack."""
    confidence_emoji = "🟢" if response.confidence > 0.8 else "🟡" if response.confidence > 0.5 else "🔴"
    
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Analysis:*\n{response.answer}"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{confidence_emoji} Confidence: {response.confidence:.2%}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"🕒 {response.timestamp}"
                }
            ]
        }
    ]

    if response.sources:
        sources_text = "\n".join([f"• {source['title']}" for source in response.sources[:3]])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Sources:*\n{sources_text}"
            }
        })

    return {"blocks": blocks}

# API endpoints
@app.post("/v1/chat/completions", response_model=Response)
async def chat_completions(query: Query, request: Request):
    """Process a query and return a response."""
    try:
        # Validate API key
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        
        api_key = auth_header.split(" ")[1]
        if api_key != os.getenv("CHARLOTTE_SERVICE_KEY"):
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Get query embedding
        query_embedding = get_embedding(query.query)
        
        # Search for relevant documents
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT title, content, 
                           embedding <=> %s as distance
                    FROM documents
                    ORDER BY distance
                    LIMIT 5
                """, (query_embedding,))
                results = cur.fetchall()

        # Format context
        context = "\n\n".join([f"Title: {r['title']}\nContent: {r['content']}" for r in results])
        
        # Generate response
        try:
            completion = openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are a security analyst assistant. Provide detailed, accurate analysis based on the context."},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuery: {query.query}"}
                ],
                max_tokens=query.max_tokens
            )
            
            answer = completion.choices[0].message.content
            confidence = min(1.0, len(context) / 1000)  # Simple confidence metric
            
            return Response(
                answer=answer,
                confidence=confidence,
                sources=[{"title": r["title"]} for r in results],
                timestamp=datetime.now().isoformat()
            )
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise HTTPException(status_code=500, detail="Failed to generate response")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "healthy"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Service unhealthy")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))