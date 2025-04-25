# Salesforce AppLink Server

This module bridges the Security Agent platform with Salesforce, enabling case creation from Slack conversations.

## Overview

The Salesforce AppLink server provides two key API endpoints:
- `/api/agentforce/security-triage`: Records security triage events
- `/api/agentforce/security-case`: Creates cases in Salesforce

## Setup Instructions

### 1. Local Development

1. Install dependencies:
   ```
   pip install -r salesforce_requirements.txt
   ```

2. Create a `.env` file with your credentials (see `salesforce.env.example`)

3. Run the server:
   ```
   python salesforce_applink.py
   ```

### 2. Heroku Deployment

1. Create a new Heroku app:
   ```
   heroku create [app-name]
   ```

2. Set environment variables:
   ```
   heroku config:set SF_USERNAME=your_salesforce_username@example.com
   heroku config:set SF_PASSWORD=your_salesforce_password
   heroku config:set SF_SECURITY_TOKEN=your_salesforce_security_token
   heroku config:set SF_DOMAIN=login
   heroku config:set API_TOKEN=your_secure_api_token
   ```

3. Deploy to Heroku:
   ```
   git add salesforce_applink.py salesforce_requirements.txt salesforce_Procfile
   git commit -m "Add Salesforce AppLink server"
   git push heroku main
   ```
   
   Note: If using a subdirectory, you may need:
   ```
   git subtree push --prefix path/to/subdirectory heroku main
   ```

4. Rename the Procfile:
   ```
   mv salesforce_Procfile Procfile
   ```

### 3. Configure Security Agent

Once deployed, update your Security Agent environment variables:

```
HEROKU_APPLINK_URL=https://your-applink-server.herokuapp.com
HEROKU_APPLINK_TOKEN=your_secure_api_token  # Same as API_TOKEN above
```

## API Endpoints

### Health Check
```
GET /health
```
Returns the status of the service and connection to Salesforce.

### Security Triage
```
POST /api/agentforce/security-triage
Authorization: Bearer your_api_token
Content-Type: application/json

{
  "incident_data": {
    "source": "Security Agent",
    "type": "Investigation",
    "details": {
      "article_id": "article_id",
      "prompt": "User prompt",
      "channel_id": "slack_channel_id",
      "thread_ts": "slack_thread_ts",
      "timestamp": "ISO timestamp"
    }
  },
  "query_text": "User query"
}
```

### Create Security Case
```
POST /api/agentforce/security-case
Authorization: Bearer your_api_token
Content-Type: application/json

{
  "case_data": {
    "source": "Security Agent",
    "type": "Security Investigation",
    "title": "Case title",
    "priority": "high|medium|low",
    "notes": "Case notes",
    "details": {
      "initial_command": "/security search query",
      "article_id": "article_id",
      "prompt": "User prompt",
      "steps": "Investigation steps",
      "channel_id": "slack_channel_id",
      "thread_ts": "slack_thread_ts",
      "slack_user_id": "slack_user_id",
      "created_at": "ISO timestamp"
    }
  }
}
```

## Salesforce Configuration

For this integration to work, your Salesforce org should:

1. Have the Case object properly configured
2. Have the security token for the user enabled
3. Have API access enabled for the user
4. Optionally, have custom fields:
   - `Slack_Channel_ID__c`
   - `Slack_Command__c`

## Troubleshooting

### Common Issues

1. **Authentication Errors**:
   - Verify SF_USERNAME, SF_PASSWORD, and SF_SECURITY_TOKEN
   - Make sure the API_TOKEN matches between Security Agent and AppLink

2. **Custom Field Errors**:
   - If custom fields aren't available, the app will log warnings but continue

3. **Connection Issues**:
   - Check network connectivity between Heroku and Salesforce
   - Ensure API access is enabled for your Salesforce user

### Logs

To view logs in Heroku:
```
heroku logs --tail
``` 