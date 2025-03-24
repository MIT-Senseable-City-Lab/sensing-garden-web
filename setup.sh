#!/bin/bash
set -e

# Create poetry environment if it doesn't exist
if [ ! -d .venv ]; then
    echo "Creating Poetry virtual environment..."
    poetry config virtualenvs.in-project true
    poetry install
fi

echo "Setup complete! You can now run the application with:"
echo "poetry run flask run --host=0.0.0.0 --port=8080"
echo "or with Docker:"
echo "docker-compose up --build"
