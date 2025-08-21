import os
import sys

# Ensure project root is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Provide dummy environment variables required for importing app
os.environ.setdefault("API_BASE_URL", "http://localhost")
os.environ.setdefault("SENSING_GARDEN_API_KEY", "dummy-key")

from app import app


def test_new_routes_exist():
    """Test that our new routes are properly defined"""
    with app.test_client() as client:
        # Test that environment route exists (will fail on API call but route should exist)
        response = client.get('/view_device/test-device/environment')
        # Should not be 404 (route exists), may be 500 due to API issues
        assert response.status_code != 404
        
        # Test that filtered download route exists
        response = client.get('/download_filtered/classifications?device_id=test&start_time=2023-01-01T00:00:00Z&end_time=2023-01-01T23:59:59Z')
        # Should not be 404 (route exists), may be 500 due to API issues  
        assert response.status_code != 404


def test_device_content_template_updated():
    """Test that device content page can be rendered with environment count"""
    with app.test_client() as client:
        # This will fail at the API call level, but we can test route registration
        response = client.get('/view_device/test-device')
        # Should not be 404, indicating the route is properly configured
        assert response.status_code != 404


def test_csv_download_parameters():
    """Test CSV download parameter validation"""
    with app.test_client() as client:
        # Test missing device_id
        response = client.get('/download_filtered/classifications')
        assert response.status_code == 400
        
        # Test missing start_time
        response = client.get('/download_filtered/classifications?device_id=test')
        assert response.status_code == 400
        
        # Test missing end_time
        response = client.get('/download_filtered/classifications?device_id=test&start_time=2023-01-01T00:00:00Z')
        assert response.status_code == 400
        
        # Test invalid table type
        response = client.get('/download_filtered/invalid_table?device_id=test&start_time=2023-01-01T00:00:00Z&end_time=2023-01-01T23:59:59Z')
        assert response.status_code == 400