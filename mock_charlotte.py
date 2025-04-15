from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values
import numpy as np
from pgvector.psycopg2 import register_vector
import anthropic
from contextlib import contextmanager

load_dotenv()

app = FastAPI(title="Mock Charlotte AI")

# Database connection configuration
DATABASE_URL = os.getenv("DATABASE_URL")

class Query(BaseModel):
    query: str
    max_tokens: Optional[int] = 500

class Response(BaseModel):
    answer: str
    confidence: float

@contextmanager
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

def setup_database():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            
            # Create security_knowledge table with vector support
            cur.execute("""
                CREATE TABLE IF NOT EXISTS security_knowledge (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding vector(1536),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for vector similarity search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS security_knowledge_embedding_idx 
                ON security_knowledge 
                USING ivfflat (embedding vector_cosine_ops)
            """)
            
            conn.commit()

def get_embedding(text: str) -> List[float]:
    """Get embedding using Anthropic's API"""
    # Initialize Anthropic client with explicit API key
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
    
    # IMPORTANT: Fixed client initialization - removed proxies if present
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    
    # Use Claude to generate embeddings
    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1536,
        system="You are an expert at converting text into high-quality semantic embeddings. For the given input, return a list of 1536 floating point numbers that represent the semantic meaning of the text. These embeddings will be used for similarity search in a security context.",
        messages=[{
            "role": "user",
            "content": f"Generate embeddings for: {text}"
        }]
    )
    
    # Parse the response into a list of floats
    try:
        # Extract numbers from the response
        embedding_text = message.content[0].text
        # Convert string representation of numbers into actual float values
        embedding = [float(num) for num in embedding_text.strip('[]').split(',')]
        # Ensure we have exactly 1536 dimensions
        if len(embedding) != 1536:
            raise ValueError(f"Expected 1536 dimensions, got {len(embedding)}")
        return embedding
    except Exception as e:
        raise ValueError(f"Failed to parse embeddings: {e}")

@app.post("/v1/chat/completions", response_model=Response)
async def mock_charlotte(query: Query):
    try:
        # Get embedding for the query
        query_embedding = get_embedding(query.query)
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Register vector type with psycopg2
                register_vector(conn)
                
                # Perform vector similarity search
                cur.execute("""
                    SELECT content, embedding <=> %s as distance
                    FROM security_knowledge
                    ORDER BY embedding <=> %s
                    LIMIT 1
                """, (query_embedding, query_embedding))
                
                result = cur.fetchone()
                
                if result:
                    content, distance = result
                    confidence = 1 - distance  # Convert distance to confidence score
                    
                    # Use Claude to enhance the response
                    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
                    if not anthropic_api_key:
                        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
                    
                    # IMPORTANT: Fixed client initialization
                    client = anthropic.Anthropic(api_key=anthropic_api_key)
                    
                    enhanced_response = client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=500,
                        system="You are a cybersecurity expert assistant. Based on the retrieved knowledge and the user's query, provide a detailed and accurate response.",
                        messages=[{
                            "role": "user",
                            "content": f"Query: {query.query}\nRetrieved Knowledge: {content}\n\nProvide a comprehensive security analysis based on this information."
                        }]
                    )
                    
                    return Response(
                        answer=enhanced_response.content[0].text,
                        confidence=confidence
                    )
                else:
                    # Fallback response using Claude
                    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
                    if not anthropic_api_key:
                        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
                    
                    # IMPORTANT: Fixed client initialization
                    client = anthropic.Anthropic(api_key=anthropic_api_key)
                    
                    fallback_response = client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=500,
                        system="You are a cybersecurity expert assistant. When no specific knowledge is available, provide a general security analysis.",
                        messages=[{
                            "role": "user",
                            "content": f"Provide a security analysis for: {query.query}"
                        }]
                    )
                    
                    return Response(
                        answer=fallback_response.content[0].text,
                        confidence=0.5
                    )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def startup_event():
    setup_database()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))