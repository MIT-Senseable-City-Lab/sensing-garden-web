#!/bin/bash
set -e

# Load environment variables from .env file if it exists
if [ -f .env ]; then
  echo "Loading environment from .env file"
  set -a
  source .env
  set +a
fi

# If PORT isn't set, default to 8080
PORT=${PORT:-8080}

# Set environment variables for local development
export FLASK_ENV=development
export FLASK_APP=app

# Check if API key is set (without printing it)
if [ -z "$SENSING_GARDEN_API_KEY" ]; then
  echo "WARNING: SENSING_GARDEN_API_KEY is not set!"
else
  echo "SENSING_GARDEN_API_KEY is set"
fi

# Start Flask with gunicorn in development mode using Poetry
echo "Starting Flask application with gunicorn on port $PORT..."
poetry run gunicorn app:app --bind 0.0.0.0:$PORT --reload
