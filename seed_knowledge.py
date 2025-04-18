import os
import logging
import argparse
from dotenv import load_dotenv
from database import DatabaseManager
from heroku_inference import InferenceClient
import psycopg2
from psycopg2.extras import execute_values

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security knowledge entries
SECURITY_KNOWLEDGE = [
    {
        "title": "Data Exfiltration Prevention",
        "content": "Implement network segmentation, monitor data transfers, and use DLP tools to prevent unauthorized data exfiltration.",
        "category": "Data Security"
    },
    {
        "title": "Phishing Detection",
        "content": "Train employees to recognize phishing attempts, implement email filtering, and use multi-factor authentication.",
        "category": "Email Security"
    },
    {
        "title": "Endpoint Protection",
        "content": "Deploy antivirus software, enable firewalls, and keep systems updated to protect endpoints from malware.",
        "category": "Endpoint Security"
    },
    {
        "title": "Incident Response",
        "content": "Follow incident response procedures: identify, contain, eradicate, recover, and learn from security incidents.",
        "category": "Incident Response"
    },
    {
        "title": "Access Control",
        "content": "Implement least privilege access, use role-based access control, and regularly review permissions.",
        "category": "Access Management"
    },
    {
        "title": "Vulnerability Management",
        "content": "Regularly scan for vulnerabilities, prioritize patching, and maintain an asset inventory.",
        "category": "Vulnerability Management"
    },
    {
        "title": "Security Monitoring",
        "content": "Deploy SIEM tools, monitor logs, and set up alerts for suspicious activities.",
        "category": "Monitoring"
    },
    {
        "title": "Compliance Management",
        "content": "Maintain compliance with relevant regulations, document controls, and conduct regular audits.",
        "category": "Compliance"
    }
]

def seed_database(cohere_key: str, anthropic_key: str = None):
    """Seed the database with initial security knowledge."""
    try:
        # Initialize Heroku Inference client
        inference_client = InferenceClient(cohere_key=cohere_key, anthropic_key=anthropic_key)
        
        # Connect to database
        load_dotenv()
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # Create table if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS security_knowledge (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                embedding vector(1024)
            )
        """)
        
        # Generate embeddings and insert data
        for knowledge in SECURITY_KNOWLEDGE:
            # Generate embedding using Cohere
            embedding = inference_client.embeddings_create(
                model="embed-english-v3.0",
                texts=[knowledge["content"]]
            )[0]
            
            # Insert knowledge with embedding
            cur.execute("""
                INSERT INTO security_knowledge (title, content, category, embedding)
                VALUES (%s, %s, %s, %s)
            """, (knowledge["title"], knowledge["content"], knowledge["category"], embedding))
        
        conn.commit()
        logger.info("Database seeded successfully")
        
    except Exception as e:
        logger.error(f"Error seeding database: {str(e)}")
        raise
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Seed the database with security knowledge.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--api-key', help='API key (for backward compatibility)')
    group.add_argument('--cohere-key', help='Cohere API key')
    parser.add_argument('--anthropic-key', help='Anthropic API key (optional)')
    args = parser.parse_args()
    
    # Use either api-key or cohere-key
    cohere_key = args.api_key or args.cohere_key
    seed_database(cohere_key, args.anthropic_key) 