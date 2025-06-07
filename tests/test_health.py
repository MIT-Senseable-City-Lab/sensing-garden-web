import os
import sys

# Ensure project root is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Provide dummy environment variables required for importing app
os.environ.setdefault("API_BASE_URL", "http://localhost")
os.environ.setdefault("SENSING_GARDEN_API_KEY", "dummy-key")

from app import app


def test_health_endpoint():
    with app.test_client() as client:
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)
        for key in ["status", "timestamp", "environment", "message"]:
            assert key in data
