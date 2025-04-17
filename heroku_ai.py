import os
import json
import logging
from typing import Dict, Optional
import subprocess

logger = logging.getLogger(__name__)

class HerokuAI:
    def __init__(self, app_name: str, model_alias: str = "claude-3-5-sonnet"):
        self.app_name = app_name
        self.model_alias = model_alias
        self._validate_heroku_cli()
    
    def _validate_heroku_cli(self) -> None:
        """Validate that Heroku CLI is installed and authenticated."""
        try:
            subprocess.run(["heroku", "--version"], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            raise RuntimeError("Heroku CLI is not installed or not in PATH")
        
        try:
            subprocess.run(["heroku", "auth:whoami"], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            raise RuntimeError("Not authenticated with Heroku CLI. Please run 'heroku login'")
    
    def _run_heroku_command(self, command: str) -> Dict:
        """Run a Heroku CLI command and return the JSON output."""
        try:
            result = subprocess.run(
                command.split(),
                check=True,
                capture_output=True,
                text=True
            )
            return json.loads(result.stdout) if result.stdout else {}
        except subprocess.CalledProcessError as e:
            logger.error(f"Heroku command failed: {e.stderr}")
            raise
        except json.JSONDecodeError:
            logger.error("Failed to parse Heroku command output as JSON")
            raise
    
    def create_model(self) -> None:
        """Create and attach the AI model to the app."""
        try:
            # Check if model already exists
            models = self._run_heroku_command(f"heroku ai:models:list --app {self.app_name}")
            if any(m["alias"] == self.model_alias for m in models):
                logger.info(f"Model {self.model_alias} already exists")
                return
            
            # Create new model
            self._run_heroku_command(
                f"heroku ai:models:create claude-3-5-sonnet --app {self.app_name} --as {self.model_alias}"
            )
            logger.info(f"Created model {self.model_alias}")
        except Exception as e:
            logger.error(f"Failed to create model: {str(e)}")
            raise
    
    def query_model(self, prompt: str, options: Optional[Dict] = None) -> Dict:
        """Query the AI model with a prompt and optional parameters."""
        try:
            # Prepare command with options
            cmd = f"heroku ai:models:call {self.model_alias} --app {self.app_name} --prompt '{prompt}'"
            if options:
                cmd += f" --opts '{json.dumps(options)}'"
            
            # Execute query
            result = self._run_heroku_command(cmd)
            logger.info(f"Successfully queried model {self.model_alias}")
            return result
        except Exception as e:
            logger.error(f"Failed to query model: {str(e)}")
            raise
    
    def get_model_info(self) -> Dict:
        """Get information about the attached model."""
        try:
            return self._run_heroku_command(
                f"heroku ai:models:info {self.model_alias} --app {self.app_name}"
            )
        except Exception as e:
            logger.error(f"Failed to get model info: {str(e)}")
            raise 