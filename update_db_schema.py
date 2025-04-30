import os
import psycopg2
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def add_guidance_column():
    """Add the guidance column to the security_knowledge table if it doesn't exist."""
    load_dotenv()
    conn = None
    try:
        # Connect to the database
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Check if the guidance column already exists
        logger.info("Checking if guidance column exists")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'security_knowledge' AND column_name = 'guidance'")
        column_exists = cursor.fetchone() is not None
        
        if column_exists:
            logger.info("Guidance column already exists in security_knowledge table")
        else:
            # Add the guidance column
            logger.info("Adding guidance column to security_knowledge table")
            cursor.execute("ALTER TABLE security_knowledge ADD COLUMN guidance TEXT")
            conn.commit()
            logger.info("Successfully added guidance column to security_knowledge table")
        
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error updating database schema: {str(e)}")
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    if add_guidance_column():
        print("Database schema updated successfully.")
    else:
        print("Failed to update database schema.") 