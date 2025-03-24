#!/bin/bash
set -e

# If PORT isn't set, default to 8080
PORT=${PORT:-8080}

echo "Starting Flask application on port $PORT..."
echo "Environment: $FLASK_ENV"
echo "Flask App: $FLASK_APP"
echo "API Base URL: $API_BASE_URL"

# Check if API key is set (without printing it)
if [ -z "$SENSING_GARDEN_API_KEY" ]; then
  echo "WARNING: SENSING_GARDEN_API_KEY is not set!"
else
  echo "SENSING_GARDEN_API_KEY is set"
fi

# Create health check status directory
mkdir -p /tmp/app_status
echo '{"status": "running"}' > /tmp/app_status/health.json

# Start Flask directly
exec python app.py
