# Sensing Garden Dashboard

A web dashboard to view data from the Sensing Garden API using the sensing_garden_client package.

## Setup Instructions

### Environment Setup

1. Create a `.env` file in the project root with the following content:

```
# API Configuration for Sensing Garden Backend
SENSING_GARDEN_API_KEY=your_api_key_here
API_BASE_URL=https://your-api-endpoint.com
```

### Option 1: Using Poetry (Local Development)

1. Install Poetry if you don't have it already:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Run the start script to create the Poetry environment:

```bash
./start_local.sh
```

3. Run the dashboard:

```bash
poetry run flask run --host=0.0.0.0 --port=8080
```

4. Open your browser and navigate to:

```
http://localhost:8080
```

### Option 2: Using Docker

1. Make sure Docker and Docker Compose are installed on your system

2. Build and run the Docker container:

```bash
docker-compose up --build
```

3. Open your browser and navigate to:

```
http://localhost:8080
```

## Features

- View detection data including images and metadata
- View classification data including species information and confidence scores
- View model information
- View detailed information for each item
- Direct links to S3 images
- Pagination support for large datasets

## Technical Details

- Uses Flask for the web framework
- Poetry for dependency management
- sensing_garden_client package to interact with the API
- Docker support for containerized deployment

## Environment Variables

The following environment variables are required (stored in the `.env` file):

- `SENSING_GARDEN_API_KEY`: API key for authentication with the Sensing Garden API
- `API_BASE_URL`: Base URL for the API

## Development

### Adding Dependencies

To add new dependencies to the project:

```bash
poetry add package-name
```

### Deploying to AWS AppRunner

This application is configured to be deployable to AWS AppRunner. The Docker container setup provides the necessary configuration for cloud deployment.

## Notes

- This dashboard is for development and testing purposes only
- For production use, consider adding authentication and additional security measures
