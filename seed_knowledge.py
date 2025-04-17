import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values
import numpy as np

load_dotenv()

# Initial security knowledge base
SECURITY_KNOWLEDGE = [
    {
        "title": "Process Creation Analysis",
        "content": "For suspicious process creation events, first identify the parent process and command line arguments. Check for unusual paths, unexpected parent-child relationships, and any associated network connections.",
        "category": "process_monitoring"
    },
    {
        "title": "Data Exfiltration Investigation",
        "content": "When investigating potential data exfiltration, analyze network traffic patterns, focusing on unusual destinations, large data transfers, and unexpected protocols. Review DNS queries and SSL/TLS certificate information.",
        "category": "network_security"
    },
    {
        "title": "Critical Security Alerts",
        "content": "Critical security alerts for junior analysts should focus on: 1) Failed authentication attempts, 2) Malware detections, 3) Suspicious PowerShell or command line activity, 4) Unusual service creations.",
        "category": "alert_management"
    },
    {
        "title": "Lateral Movement Detection",
        "content": "Best practices for lateral movement investigation include: monitoring for remote administration tool usage, analyzing authentication logs across systems, identifying unusual account behavior, and mapping network connections between hosts.",
        "category": "threat_detection"
    },
    {
        "title": "Indicators of Compromise",
        "content": "Common indicators of compromise include: unexpected outbound connections, unusual process hierarchy, modification of system files, creation of scheduled tasks, and changes to startup registry keys.",
        "category": "threat_detection"
    },
    {
        "title": "Ransomware Analysis",
        "content": "When analyzing potential ransomware activity, look for: mass file modifications, suspicious encryption processes, deletion of volume shadow copies, and attempts to disable security tools.",
        "category": "malware_analysis"
    },
    {
        "title": "Privilege Escalation Investigation",
        "content": "For privilege escalation investigation, focus on: new service creation, scheduled task modification, unusual process elevation, and unexpected admin group changes.",
        "category": "threat_detection"
    },
    {
        "title": "Network Security Monitoring",
        "content": "Network security monitoring should prioritize: unusual protocol usage, large data transfers to unknown destinations, DNS tunneling attempts, and encrypted traffic to uncommon destinations.",
        "category": "network_security"
    }
]

def get_db_connection():
    """Get a database connection."""
    return psycopg2.connect(os.getenv('DATABASE_URL'))

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
                        title VARCHAR(255) NOT NULL,
                        content TEXT NOT NULL,
                        category VARCHAR(100) NOT NULL,
                        embedding vector(1536),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Generate dummy embeddings (all zeros) and insert data
                for knowledge in SECURITY_KNOWLEDGE:
                    # Create a dummy embedding (all zeros)
                    dummy_embedding = np.zeros(1536).tolist()
                    cur.execute(
                        "INSERT INTO security_knowledge (title, content, category, embedding) VALUES (%s, %s, %s, %s)",
                        (knowledge["title"], knowledge["content"], knowledge["category"], dummy_embedding)
                    )
                
                conn.commit()
                print(f"Successfully seeded database with {len(SECURITY_KNOWLEDGE)} entries (with dummy embeddings)")
                
    except Exception as e:
        print(f"Error seeding database: {e}")

if __name__ == "__main__":
    seed_database() 