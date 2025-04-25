from flask import Flask, request, jsonify
import requests
import os
import json
from simple_salesforce import Salesforce
from functools import wraps
from datetime import datetime
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Authentication middleware
def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            logger.warning(f"Missing or invalid Authorization header: {auth_header}")
            return jsonify({"error": "Unauthorized"}), 401
        
        token = auth_header.split(' ')[1]
        expected_token = os.environ.get('API_TOKEN')
        if token != expected_token:
            logger.warning(f"Invalid token provided. Expected: {expected_token[:3]}...{expected_token[-3:] if expected_token else 'None'}")
            return jsonify({"error": "Invalid token"}), 401
            
        return f(*args, **kwargs)
    return decorated

# Salesforce connection function
def get_salesforce_connection():
    try:
        username = os.environ.get('SF_USERNAME')
        password = os.environ.get('SF_PASSWORD')
        security_token = os.environ.get('SF_SECURITY_TOKEN')
        domain = os.environ.get('SF_DOMAIN', 'login')  # 'login' or 'test'
        
        logger.info(f"Connecting to Salesforce as {username} on domain {domain}")
        
        sf = Salesforce(
            username=username,
            password=password,
            security_token=security_token,
            domain=domain
        )
        return sf
    except Exception as e:
        logger.error(f"Error connecting to Salesforce: {e}")
        raise

# Root endpoint
@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "service": "Salesforce AppLink Server",
        "status": "running",
        "endpoints": [
            "/api/agentforce/security-triage",
            "/api/agentforce/security-case",
            "/health"
        ]
    })

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    # Check if we can connect to Salesforce
    try:
        sf = get_salesforce_connection()
        sf.describe()
        salesforce_status = "connected"
    except Exception as e:
        salesforce_status = f"error: {str(e)}"
    
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "salesforce": salesforce_status
    })

# 1. Security Triage Endpoint
@app.route('/api/agentforce/security-triage', methods=['POST'])
@auth_required
def security_triage():
    try:
        # Get the request data
        data = request.json
        logger.info(f"Received security triage data: {json.dumps(data)[:200]}...")
        
        # This endpoint can simply log the data
        # You could also store it in a database if needed
        
        return jsonify({
            "success": True,
            "message": "Security triage information received",
            "timestamp": datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Error processing security triage: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# 2. Security Case Creation Endpoint
@app.route('/api/agentforce/security-case', methods=['POST'])
def create_security_case():
    # Log the payload
    data = request.json
    logger.info(f"Received security case payload: {json.dumps(data)[:200]}...")
    
    # Just return a success response for the demo
    return jsonify({
        "success": True,
        "case_id": "demo-case-001",
        "case_number": "DEMO-001",
        "message": "Demo mode: Payload received successfully"
    })

if __name__ == '__main__':
    # Get port from environment variable or use 5000 as default
    port = int(os.environ.get('PORT', 5000))
    
    # Log startup information
    logger.info(f"Starting Salesforce AppLink Server on port {port}")
    logger.info(f"API_TOKEN configured: {'Yes' if os.environ.get('API_TOKEN') else 'No'}")
    logger.info(f"SF_USERNAME configured: {'Yes' if os.environ.get('SF_USERNAME') else 'No'}")
    logger.info(f"SF_PASSWORD configured: {'Yes' if os.environ.get('SF_PASSWORD') else 'No'}")
    logger.info(f"SF_SECURITY_TOKEN configured: {'Yes' if os.environ.get('SF_SECURITY_TOKEN') else 'No'}")
    
    # Start the server
    app.run(host='0.0.0.0', port=port) 