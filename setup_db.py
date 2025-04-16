"""
Modified setup script to avoid Anthropic client issues
"""
import os
import psycopg2
from psycopg2.extras import execute_values
from contextlib import contextmanager
import numpy as np
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Database connection configuration
DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

def setup_database():
    """Set up the database with all required tables and extensions."""
    try:
        # Connect to the database
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        conn.autocommit = True
        cur = conn.cursor()
        
        # Enable required extensions
        logger.info("Enabling database extensions...")
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        
        # Create documents table for RAG
        logger.info("Creating documents table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding vector(1536),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create incidents table
        logger.info("Creating incidents table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                severity TEXT NOT NULL DEFAULT 'medium',
                created_by TEXT NOT NULL,
                assigned_to TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP WITH TIME ZONE,
                metadata JSONB DEFAULT '{}'::jsonb
            )
        """)
        
        # Create incident_history table
        logger.info("Creating incident_history table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS incident_history (
                id SERIAL PRIMARY KEY,
                incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                performed_by TEXT NOT NULL,
                details JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create user_interactions table
        logger.info("Creating user_interactions table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_interactions (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                interaction_type TEXT NOT NULL,
                query TEXT,
                response TEXT,
                confidence FLOAT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB DEFAULT '{}'::jsonb
            )
        """)
        
        # Create command_history table
        logger.info("Creating command_history table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS command_history (
                id SERIAL PRIMARY KEY,
                command TEXT NOT NULL,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                arguments JSONB DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'success',
                error_message TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        logger.info("Creating indexes...")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS documents_embedding_idx 
            ON documents USING ivfflat (embedding vector_cosine_ops)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS incidents_status_idx 
            ON incidents(status)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS incidents_created_at_idx 
            ON incidents(created_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS user_interactions_user_id_idx 
            ON user_interactions(user_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS command_history_user_id_idx 
            ON command_history(user_id)
        """)
        
        # Create functions
        logger.info("Creating database functions...")
        cur.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)
        
        # Create triggers
        logger.info("Creating triggers...")
        cur.execute("""
            CREATE TRIGGER update_documents_updated_at
            BEFORE UPDATE ON documents
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """)
        cur.execute("""
            CREATE TRIGGER update_incidents_updated_at
            BEFORE UPDATE ON incidents
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """)
        
        logger.info("Database setup completed successfully!")
        
    except Exception as e:
        logger.error(f"Error setting up database: {e}")
        raise
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

# Initial security knowledge base
SECURITY_KNOWLEDGE = [
    "For suspicious process creation events, first identify the parent process and command line arguments. Check for unusual paths, unexpected parent-child relationships, and any associated network connections.",
    
    "When investigating potential data exfiltration, analyze network traffic patterns, focusing on unusual destinations, large data transfers, and unexpected protocols. Review DNS queries and SSL/TLS certificate information.",
    
    "Critical security alerts for junior analysts should focus on: 1) Failed authentication attempts, 2) Malware detections, 3) Suspicious PowerShell or command line activity, 4) Unusual service creations.",
    
    "Best practices for lateral movement investigation include: monitoring for remote administration tool usage, analyzing authentication logs across systems, identifying unusual account behavior, and mapping network connections between hosts.",
    
    "Common indicators of compromise include: unexpected outbound connections, unusual process hierarchy, modification of system files, creation of scheduled tasks, and changes to startup registry keys.",
    
    "When analyzing potential ransomware activity, look for: mass file modifications, suspicious encryption processes, deletion of volume shadow copies, and attempts to disable security tools.",
    
    "For privilege escalation investigation, focus on: new service creation, scheduled task modification, unusual process elevation, and unexpected admin group changes.",
    
    "Network security monitoring should prioritize: unusual protocol usage, large data transfers to unknown destinations, DNS tunneling attempts, and encrypted traffic to uncommon destinations."
]

def seed_database():
    """Populate the database with initial security knowledge without using embeddings"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Enable pgvector extension and create table if not exists
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS security_knowledge (
                        id SERIAL PRIMARY KEY,
                        content TEXT NOT NULL,
                        embedding vector(1536),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Generate dummy embeddings (all zeros) and insert data
                for knowledge in SECURITY_KNOWLEDGE:
                    # Create a dummy embedding (all zeros)
                    dummy_embedding = np.zeros(1536).tolist()
                    cur.execute(
                        "INSERT INTO security_knowledge (content, embedding) VALUES (%s, %s)",
                        (knowledge, dummy_embedding)
                    )
                
                conn.commit()
                print(f"Successfully seeded database with {len(SECURITY_KNOWLEDGE)} entries (with dummy embeddings)")
                
    except Exception as e:
        print(f"Error seeding database: {e}")

if __name__ == "__main__":
    print("Setting up database...")
    setup_database()
    print("Seeding initial data...")
    seed_database()
    print("Setup complete!")