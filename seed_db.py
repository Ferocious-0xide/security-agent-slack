#!/usr/bin/env python
import os
import logging
from dotenv import load_dotenv
from database import DatabaseManager
from heroku_inference import InferenceClient
import psycopg2
from psycopg2.extras import execute_values
from seed_knowledge import SECURITY_KNOWLEDGE

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def seed_database():
    """Seed the database with all 25 security knowledge articles and create vector embeddings."""
    load_dotenv()
    
    conn = None
    cur = None
    try:
        # Initialize the Inference client for embeddings
        client = InferenceClient()
        
        # Connect to the database
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        conn.autocommit = False
        cur = conn.cursor()
        
        # Check if pgvector extension is enabled
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        vector_enabled = cur.fetchone() is not None
        
        if not vector_enabled:
            try:
                # Enable vector extension
                conn.autocommit = True
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                vector_enabled = True
                logger.info("Successfully enabled vector extension")
            except Exception as e:
                logger.warning(f"Could not enable vector extension: {e}")
                logger.warning("Continuing without vector embeddings")
            finally:
                conn.autocommit = False
        
        # Get existing articles to avoid duplicates
        cur.execute("SELECT title FROM security_knowledge")
        existing_titles = {row[0] for row in cur.fetchall()}
        logger.info(f"Found {len(existing_titles)} existing knowledge articles")
        
        # Insert knowledge entries one by one
        inserted_count = 0
        for knowledge in SECURITY_KNOWLEDGE:
            title = knowledge["title"]
            content = knowledge["content"]
            category = knowledge["category"]
            
            # Skip if article already exists
            if title in existing_titles:
                logger.info(f"Skipping existing article: {title}")
                continue
                
            try:
                embedding = None
                if vector_enabled:
                    # Generate embedding using the inference client
                    try:
                        embeddings = client.embeddings_create(
                            model=os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual"),
                            texts=[content]
                        )
                        if embeddings and len(embeddings) > 0:
                            embedding = embeddings[0]
                            logger.info(f"Generated embedding for {title}")
                    except Exception as e:
                        logger.warning(f"Could not generate embedding for {title}: {e}")
                
                # Insert with or without embedding
                if vector_enabled and embedding:
                    cur.execute("""
                        INSERT INTO security_knowledge (title, content, category, embedding)
                        VALUES (%s, %s, %s, %s::vector)
                    """, (title, content, category, embedding))
                else:
                    cur.execute("""
                        INSERT INTO security_knowledge (title, content, category)
                        VALUES (%s, %s, %s)
                    """, (title, content, category))
                
                conn.commit()
                inserted_count += 1
                logger.info(f"Inserted article: {title}")
                
            except Exception as e:
                conn.rollback()
                logger.error(f"Error inserting article '{title}': {e}")
        
        # Create index on embedding vector if needed
        if vector_enabled:
            try:
                conn.autocommit = True
                # First check if index exists
                cur.execute("""
                    SELECT 1 FROM pg_indexes 
                    WHERE indexname = 'security_knowledge_embedding_idx'
                """)
                index_exists = cur.fetchone() is not None
                
                if not index_exists:
                    cur.execute("""
                        CREATE INDEX security_knowledge_embedding_idx 
                        ON security_knowledge USING ivfflat (embedding vector_cosine_ops);
                    """)
                    logger.info("Created vector index for similarity search")
            except Exception as e:
                logger.warning(f"Could not create vector index: {e}")
            finally:
                conn.autocommit = False
        
        logger.info(f"Successfully inserted {inserted_count} new security knowledge articles")
        
        # Get total count of articles in database
        cur.execute("SELECT COUNT(*) FROM security_knowledge")
        total_count = cur.fetchone()[0]
        logger.info(f"Total security knowledge articles in database: {total_count}")
        
    except Exception as e:
        if conn and not conn.closed:
            conn.rollback()
        logger.error(f"Error seeding database: {str(e)}")
        raise
    finally:
        if cur and not cur.closed:
            cur.close()
        if conn and not conn.closed:
            conn.close()

def update_existing_embeddings():
    """Update embeddings for existing articles that don't have them"""
    load_dotenv()
    
    conn = None
    cur = None
    try:
        # Initialize the Inference client for embeddings
        client = InferenceClient()
        
        # Connect to the database
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        conn.autocommit = False
        cur = conn.cursor()
        
        # Check if vector extension is enabled
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        vector_enabled = cur.fetchone() is not None
        
        if not vector_enabled:
            logger.error("Vector extension not enabled, cannot update embeddings")
            return
        
        # Get articles without embeddings
        cur.execute("SELECT id, title, content FROM security_knowledge WHERE embedding IS NULL")
        articles = cur.fetchall()
        logger.info(f"Found {len(articles)} articles without embeddings")
        
        # Update embeddings
        updated_count = 0
        for article_id, title, content in articles:
            try:
                # Generate embedding
                embeddings = client.embeddings_create(
                    model=os.getenv("EMBEDDING_MODEL_ID", "cohere-embed-multilingual"),
                    texts=[content]
                )
                if embeddings and len(embeddings) > 0:
                    embedding = embeddings[0]
                    
                    # Update the article with the embedding
                    cur.execute("""
                        UPDATE security_knowledge 
                        SET embedding = %s::vector 
                        WHERE id = %s
                    """, (embedding, article_id))
                    
                    conn.commit()
                    updated_count += 1
                    logger.info(f"Updated embedding for article {article_id}: {title}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Error updating embedding for article {article_id}: {e}")
        
        logger.info(f"Successfully updated embeddings for {updated_count} articles")
        
    except Exception as e:
        if conn and not conn.closed:
            conn.rollback()
        logger.error(f"Error updating embeddings: {str(e)}")
    finally:
        if cur and not cur.closed:
            cur.close()
        if conn and not conn.closed:
            conn.close()

if __name__ == "__main__":
    seed_database()
    update_existing_embeddings() 