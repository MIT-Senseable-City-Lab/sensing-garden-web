import os
import sys
from datetime import datetime, timedelta, timezone

# Ensure project root is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Provide dummy environment variables required for importing app
os.environ.setdefault("API_BASE_URL", "http://localhost")
os.environ.setdefault("SENSING_GARDEN_API_KEY", "dummy-key")

from app import app


def test_date_validation_start_after_end():
    """Test that start date after end date returns error"""
    with app.test_client() as client:
        response = client.get('/download_filtered/classifications', query_string={
            'device_id': 'test-device',
            'start_time': '2025-08-14T00:00:00Z',  # August 14, 2025
            'end_time': '2025-05-01T23:59:59Z'    # May 1, 2025 (earlier)
        })
        
        assert response.status_code == 400
        data = response.get_json()
        assert 'Start date must be before end date' in data['error']


def test_date_validation_same_date():
    """Test that same start and end date returns error"""
    with app.test_client() as client:
        response = client.get('/download_filtered/classifications', query_string={
            'device_id': 'test-device',
            'start_time': '2025-05-01T00:00:00Z',
            'end_time': '2025-05-01T00:00:00Z'  # Exact same datetime
        })
        
        assert response.status_code == 400
        data = response.get_json()
        assert 'Start date must be before end date' in data['error']


def test_date_validation_large_range():
    """Test that date range over 365 days returns error"""
    with app.test_client() as client:
        start_date = datetime.now(timezone.utc) - timedelta(days=400)
        end_date = datetime.now(timezone.utc) - timedelta(days=1)
        
        response = client.get('/download_filtered/classifications', query_string={
            'device_id': 'test-device',
            'start_time': start_date.isoformat(),
            'end_time': end_date.isoformat()
        })
        
        assert response.status_code == 400
        data = response.get_json()
        assert 'Date range cannot exceed 365 days' in data['error']


def test_date_validation_future_date():
    """Test that future end date returns error"""
    with app.test_client() as client:
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        next_week = datetime.now(timezone.utc) + timedelta(days=7)
        
        response = client.get('/download_filtered/classifications', query_string={
            'device_id': 'test-device',
            'start_time': tomorrow.isoformat(),
            'end_time': next_week.isoformat()
        })
        
        assert response.status_code == 400
        data = response.get_json()
        assert 'End date cannot be in the future' in data['error']


def test_date_validation_valid_range():
    """Test that valid date range passes validation (will fail on API call but not validation)"""
    with app.test_client() as client:
        start_date = datetime.now(timezone.utc) - timedelta(days=7)
        end_date = datetime.now(timezone.utc) - timedelta(days=1)
        
        response = client.get('/download_filtered/classifications', query_string={
            'device_id': 'test-device',
            'start_time': start_date.isoformat(),
            'end_time': end_date.isoformat()
        })
        
        # Should not be 400 (validation error), may be 500 due to API call failure
        assert response.status_code != 400


def test_date_validation_invalid_format():
    """Test that invalid date format returns error"""
    with app.test_client() as client:
        response = client.get('/download_filtered/classifications', query_string={
            'device_id': 'test-device',
            'start_time': 'invalid-date',
            'end_time': '2025-05-01T23:59:59Z'
        })
        
        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid date format' in data['error']