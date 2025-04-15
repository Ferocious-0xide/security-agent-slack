import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values
import openai
from mock_charlotte import get_db_connection, get_embedding

load_dotenv()

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
    """Populate the database with initial security knowledge"""
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
                
                # Generate embeddings and insert data
                for knowledge in SECURITY_KNOWLEDGE:
                    embedding = get_embedding(knowledge)
                    cur.execute(
                        "INSERT INTO security_knowledge (content, embedding) VALUES (%s, %s)",
                        (knowledge, embedding)
                    )
                
                conn.commit()
                print(f"Successfully seeded database with {len(SECURITY_KNOWLEDGE)} entries")
                
    except Exception as e:
        print(f"Error seeding database: {e}")

if __name__ == "__main__":
    seed_database() 