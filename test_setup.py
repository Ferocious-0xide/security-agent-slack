import os
import sys
import psycopg2
import requests
import logging
from dotenv import load_dotenv
from typing import Dict, Any, List
import json
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class SetupTester:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.service_url = os.getenv("CHARLOTTE_SERVICE_URL")
        self.service_key = os.getenv("CHARLOTTE_SERVICE_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.slack_app_token = os.getenv("SLACK_APP_TOKEN")

    def test_environment_variables(self) -> bool:
        """Test if all required environment variables are set."""
        required_vars = [
            "DATABASE_URL",
            "CHARLOTTE_SERVICE_URL",
            "CHARLOTTE_SERVICE_KEY",
            "OPENAI_API_KEY",
            "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN"
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
            return False
        
        logger.info("All environment variables are set")
        return True

    def test_database_connection(self) -> bool:
        """Test database connection and verify tables exist."""
        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()
            
            # Check required tables
            required_tables = [
                "documents",
                "incidents",
                "incident_history",
                "user_interactions",
                "command_history"
            ]
            
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            existing_tables = {row[0] for row in cur.fetchall()}
            
            missing_tables = [table for table in required_tables if table not in existing_tables]
            if missing_tables:
                logger.error(f"Missing database tables: {', '.join(missing_tables)}")
                return False
            
            # Check extensions
            cur.execute("SELECT extname FROM pg_extension")
            extensions = {row[0] for row in cur.fetchall()}
            required_extensions = {"vector", "pgcrypto"}
            
            missing_extensions = required_extensions - extensions
            if missing_extensions:
                logger.error(f"Missing database extensions: {', '.join(missing_extensions)}")
                return False
            
            logger.info("Database connection and tables verified")
            return True
            
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
        finally:
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                conn.close()

    def test_charlotte_service(self) -> bool:
        """Test if the Charlotte service is running and responding."""
        try:
            response = requests.post(
                f"{self.service_url}/health",
                headers={"Authorization": f"Bearer {self.service_key}"}
            )
            response.raise_for_status()
            
            if response.json().get("status") == "healthy":
                logger.info("Charlotte service is healthy")
                return True
            else:
                logger.error("Charlotte service returned unexpected status")
                return False
                
        except Exception as e:
            logger.error(f"Charlotte service test failed: {e}")
            return False

    def test_openai_connection(self) -> bool:
        """Test OpenAI API connection."""
        try:
            import openai
            client = openai.OpenAI(api_key=self.openai_key)
            client.models.list()
            logger.info("OpenAI connection verified")
            return True
        except Exception as e:
            logger.error(f"OpenAI connection test failed: {e}")
            return False

    def test_slack_connection(self) -> bool:
        """Test Slack API connection."""
        try:
            response = requests.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {self.slack_bot_token}"}
            )
            response.raise_for_status()
            
            if response.json().get("ok"):
                logger.info("Slack connection verified")
                return True
            else:
                logger.error("Slack connection test failed")
                return False
                
        except Exception as e:
            logger.error(f"Slack connection test failed: {e}")
            return False

    def test_rag_functionality(self) -> bool:
        """Test RAG functionality with a simple query."""
        try:
            response = requests.post(
                f"{self.service_url}/v1/chat/completions",
                json={
                    "query": "What are common indicators of compromise?",
                    "max_tokens": 100
                },
                headers={"Authorization": f"Bearer {self.service_key}"}
            )
            response.raise_for_status()
            
            result = response.json()
            if "answer" in result and "confidence" in result:
                logger.info("RAG functionality verified")
                return True
            else:
                logger.error("RAG response missing required fields")
                return False
                
        except Exception as e:
            logger.error(f"RAG functionality test failed: {e}")
            return False

    def run_all_tests(self) -> bool:
        """Run all tests and return overall status."""
        tests = [
            ("Environment Variables", self.test_environment_variables),
            ("Database Connection", self.test_database_connection),
            ("Charlotte Service", self.test_charlotte_service),
            ("OpenAI Connection", self.test_openai_connection),
            ("Slack Connection", self.test_slack_connection),
            ("RAG Functionality", self.test_rag_functionality)
        ]
        
        all_passed = True
        for test_name, test_func in tests:
            logger.info(f"Running test: {test_name}")
            if not test_func():
                all_passed = False
                logger.error(f"Test failed: {test_name}")
            time.sleep(1)  # Add delay between tests
        
        if all_passed:
            logger.info("All tests passed successfully!")
        else:
            logger.error("Some tests failed. Check the logs above for details.")
        
        return all_passed

def main():
    tester = SetupTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 