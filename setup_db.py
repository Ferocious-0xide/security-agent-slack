"""
Modified setup script to avoid Anthropic client issues
"""
import os
import psycopg2
from psycopg2.extras import execute_values
from contextlib import contextmanager
import numpy as np

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