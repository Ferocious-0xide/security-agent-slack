# Salesforce Integration Guide

This document provides detailed instructions for setting up the Salesforce integration with the Security Agent platform using Heroku AppLink.

## Overview

The Security Agent platform integrates with Salesforce to create security cases based on Slack interactions. When a security analyst uses the `/security search` command and follows up with the "Ask Charlotte" button for investigation steps, they can then create a case in Salesforce with a single click.

## Architecture

```
+----------------+    +-------------------+    +-------------------+
|                |    |                   |    |                   |
|  Slack         |    |  Security Agent   |    |  Heroku AppLink   |
|  Workspace     +--->+  Platform         +--->+  Integration      |
|                |    |                   |    |                   |
+----------------+    +-------------------+    +--------+----------+
                                                        |
                                                        v
                                              +-------------------+
                                              |                   |
                                              |  Salesforce       |
                                              |  Platform         |
                                              |                   |
                                              +-------------------+
```

## Setup Instructions

### 1. Configure Environment Variables

Add the following environment variables to your Security Agent deployment:

```
# Heroku AppLink Configuration
HEROKU_APPLINK_URL=https://your-applink-instance.herokuapp.com
HEROKU_APPLINK_TOKEN=your-secure-token
```

### 2. Set Up Heroku AppLink

1. Create a new Heroku app to serve as your AppLink integration
2. Deploy a simple Express.js or Flask application with the following endpoints:
   - `/api/agentforce/security-case`: Creates security cases in Salesforce
   - `/api/agentforce/security-triage`: Handles security triage events
3. Configure the AppLink with your Salesforce credentials

### 3. Create Salesforce Flow

1. In Salesforce Setup, navigate to Flow Builder
2. Create a new Flow with an API trigger
3. Configure the Flow to:
   - Accept the payload from the Security Agent
   - Create a Case record with the following fields:
     - Subject: Case title from the payload
     - Priority: Case priority from the payload
     - Description: Case notes and investigation steps
     - Custom fields for Slack channel ID, original command, etc.
4. Activate the Flow

### 4. Test the Integration

1. Use the `/security search <query>` command in Slack
2. When the results appear, click on the "Ask Charlotte" button
3. In the modal, enter or edit your prompt and submit
4. When Charlotte's investigation steps appear, click the "Create Security Case" button
5. Fill in the case details in the modal and submit
6. Verify that the case is created in Salesforce with the correct information

## Payload Format

The Security Agent sends the following payload to Salesforce:

```json
{
  "case_data": {
    "source": "Security Agent",
    "type": "Security Investigation",
    "title": "Case title entered by user",
    "priority": "high|medium|low",
    "notes": "Additional notes entered by user",
    "details": {
      "initial_command": "/security search original query",
      "article_id": "knowledge_article_id",
      "prompt": "User prompt for Charlotte",
      "steps": "Investigation steps from Charlotte",
      "channel_id": "slack_channel_id",
      "thread_ts": "slack_thread_timestamp",
      "slack_user_id": "slack_user_id",
      "created_at": "ISO timestamp"
    }
  }
}
```

## Heroku AppLink Implementation Example

Here's a simple example of how the Heroku AppLink server might handle the incoming security case request:

```javascript
const express = require('express');
const jsforce = require('jsforce');
const app = express();
app.use(express.json());

// Salesforce connection
const conn = new jsforce.Connection({
  loginUrl: process.env.SF_LOGIN_URL || 'https://login.salesforce.com'
});

// Authentication middleware
const authMiddleware = (req, res, next) => {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  
  const token = authHeader.split(' ')[1];
  if (token !== process.env.API_TOKEN) {
    return res.status(401).json({ error: 'Invalid token' });
  }
  
  next();
};

// Authenticate with Salesforce
const connectToSalesforce = async () => {
  try {
    await conn.login(process.env.SF_USERNAME, process.env.SF_PASSWORD);
    console.log('Connected to Salesforce');
  } catch (err) {
    console.error('Salesforce connection error:', err);
  }
};

connectToSalesforce();

// Endpoint to create security case
app.post('/api/agentforce/security-case', authMiddleware, async (req, res) => {
  try {
    const { case_data } = req.body;
    
    // Create case in Salesforce
    const caseRecord = {
      Subject: case_data.title,
      Priority: case_data.priority.charAt(0).toUpperCase() + case_data.priority.slice(1),
      Description: case_data.notes,
      Origin: 'Slack',
      Type: 'Security Investigation',
      Slack_Channel_ID__c: case_data.details.channel_id,
      Slack_Command__c: case_data.details.initial_command,
      Investigation_Steps__c: case_data.details.steps
    };
    
    const result = await conn.sobject('Case').create(caseRecord);
    
    if (result.success) {
      // Get the case number
      const caseInfo = await conn.sobject('Case').retrieve(result.id);
      
      res.status(200).json({
        success: true,
        case_id: result.id,
        case_number: caseInfo.CaseNumber
      });
    } else {
      res.status(400).json({
        success: false,
        error: result.errors
      });
    }
  } catch (err) {
    console.error('Error creating case:', err);
    res.status(500).json({
      success: false,
      error: err.message
    });
  }
});

// Start server
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
```

## Troubleshooting

### Common Issues

1. **Authentication Errors**:
   - Verify that your Salesforce credentials are correct
   - Check that the `HEROKU_APPLINK_TOKEN` matches between the Security Agent and AppLink server

2. **Payload Format Errors**:
   - Ensure the payload matches the expected format in your Salesforce Flow
   - Check the Heroku logs for any errors parsing the payload

3. **Flow Execution Errors**:
   - Review the Salesforce Flow debug logs
   - Ensure all required fields in Salesforce are being populated correctly

### Logging

Enable detailed logging in both the Security Agent and AppLink server to help diagnose issues:

```javascript
// In your AppLink server
app.post('/api/agentforce/security-case', authMiddleware, async (req, res) => {
  console.log('Received security case request:', JSON.stringify(req.body));
  // Rest of the code...
});
```

## Support

For issues with the Salesforce integration, please:
1. Check the Security Agent logs for any errors
2. Review the Heroku AppLink server logs
3. Verify the Salesforce Flow execution logs
4. Create an issue in the GitHub repository with detailed information 