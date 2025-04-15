# Security Analyst Prompt Suggestion Agent

This agent provides automated prompt suggestions for junior security analysts by leveraging CrowdStrike's Charlotte AI and posting to a Slack channel.

## Prerequisites

- Heroku account
- Slack workspace with bot integration
- CrowdStrike Charlotte AI access

## Setup

1. Clone this repository
2. Copy `.env.example` to `.env` and fill in your credentials:
   - `SLACK_BOT_TOKEN`: Your Slack bot token
   - `SLACK_CHANNEL_ID`: The ID of your target Slack channel
   - `CHARLOTTE_API_KEY`: Your CrowdStrike Charlotte AI API key
   - `CHARLOTTE_API_ENDPOINT`: CrowdStrike Charlotte AI endpoint
   - `SUGGESTION_INTERVAL_MINUTES`: How often to post suggestions (default: 30)

## Deployment to Heroku

1. Create a new Heroku app:
   ```bash
   heroku create
   ```

2. Set environment variables:
   ```bash
   heroku config:set SLACK_BOT_TOKEN=your-token
   heroku config:set SLACK_CHANNEL_ID=your-channel-id
   heroku config:set CHARLOTTE_API_KEY=your-api-key
   heroku config:set CHARLOTTE_API_ENDPOINT=your-endpoint
   heroku config:set SUGGESTION_INTERVAL_MINUTES=30
   ```

3. Deploy:
   ```bash
   git push heroku main
   ```

4. Ensure the worker is running:
   ```bash
   heroku ps:scale worker=1
   ```

## Features

- Automated security analysis prompt suggestions
- Integration with CrowdStrike Charlotte AI for relevant insights
- Regular posting to Slack channel
- Configurable posting interval
- Error handling and logging

## Monitoring

Monitor the application logs using:
```bash
heroku logs --tail
``` 