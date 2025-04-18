import os
import logging
from dotenv import load_dotenv
from database import DatabaseManager
from heroku_inference import InferenceClient
import psycopg2
from psycopg2.extras import execute_values

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Security knowledge entries
SECURITY_KNOWLEDGE = [
    {
        "title": "Data Exfiltration Prevention",
        "content": "Implement network segmentation, monitor data transfers, and use DLP tools to prevent unauthorized data exfiltration.",
        "category": "Network Security"
    },
    {
        "title": "Access Control Best Practices",
        "content": "Enforce strong password policies, implement MFA, and regularly audit access permissions to maintain security.",
        "category": "Access Control"
    },
    {
        "title": "Incident Response Plan",
        "content": "Develop and maintain an incident response plan that includes clear roles, communication protocols, and recovery procedures.",
        "category": "Incident Response"
    },
    {
        "title": "Secure Configuration",
        "content": "Follow security hardening guidelines, disable unnecessary services, and regularly update system configurations.",
        "category": "System Security"
    },
    {
        "title": "Security Monitoring",
        "content": "Implement comprehensive logging, use SIEM solutions, and conduct regular security assessments.",
        "category": "Security Operations"
    },
    {
        "title": "Vulnerability Management",
        "content": "Regularly scan for vulnerabilities, prioritize patches, and maintain an up-to-date inventory of assets.",
        "category": "Vulnerability Management"
    },
    {
        "title": "Security Awareness",
        "content": "Conduct regular security training, simulate phishing attacks, and promote security-conscious behavior.",
        "category": "Security Training"
    },
    {
        "title": "Compliance Requirements",
        "content": "Stay updated with regulatory requirements, perform regular audits, and maintain documentation of security controls.",
        "category": "Compliance"
    }
]

def seed_database():
    """Seed the database with security knowledge."""
    try:
        # Initialize the OpenAI client
        client = InferenceClient()
        
        # Connect to the database
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        cur = conn.cursor()

        # Enable the vector extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        # Drop existing tables
        cur.execute("DROP TABLE IF EXISTS incident_knowledge_references CASCADE")
        cur.execute("DROP TABLE IF EXISTS security_knowledge CASCADE")

        # Create the security_knowledge table with vector(1024) for Cohere embeddings
        cur.execute("""
            CREATE TABLE security_knowledge (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                embedding vector(1024)
            )
        """)

        # Create the incident_knowledge_references table
        cur.execute("""
            CREATE TABLE incident_knowledge_references (
                id SERIAL PRIMARY KEY,
                incident_id UUID REFERENCES incidents(id),
                knowledge_id INTEGER REFERENCES security_knowledge(id),
                relevance_score FLOAT
            )
        """)

        # Insert knowledge entries and generate embeddings
        for knowledge in SECURITY_KNOWLEDGE:
            # Generate embedding for the content
            embeddings = client.embeddings_create(
                model="cohere-embed-multilingual",
                texts=[knowledge["content"]]
            )
            embedding = embeddings[0]

            # Insert the knowledge entry with its embedding
            cur.execute("""
                INSERT INTO security_knowledge (title, content, category, embedding)
                VALUES (%s, %s, %s, %s::vector)
            """, (knowledge["title"], knowledge["content"], knowledge["category"], embedding))

        # Commit the changes
        conn.commit()
        logger.info("Successfully seeded the database with security knowledge")

    except Exception as e:
        logger.error(f"Error seeding database: {str(e)}")
        raise
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    load_dotenv()
    seed_database() 