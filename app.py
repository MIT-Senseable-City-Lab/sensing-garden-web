import csv
import io
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import (Flask, jsonify, make_response, redirect, render_template,
                  request, url_for)
import requests
from sensing_garden_client import SensingGardenClient
import boto3
from collections import defaultdict

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Create client instance
client = SensingGardenClient(
    base_url=os.getenv('API_BASE_URL'),
    api_key=os.getenv('SENSING_GARDEN_API_KEY'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    aws_region=os.getenv('AWS_REGION')
)

def fetch_data(
    table_type: str,
    device_id: Optional[str] = None,
    next_token: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_desc: Optional[bool] = False,
    limit: int = 50,
) -> Dict[str, Any]:
    """Fetch data from the API for a specific table with pagination support."""
    try:
        if table_type == 'classifications':
            response = client.classifications.fetch(
                device_id=device_id,
                limit=limit,
                next_token=next_token,
                sort_by=sort_by,
                sort_desc=sort_desc
            )
        elif table_type == 'models':
            response = client.models.fetch(
                limit=limit,
                next_token=next_token,
                sort_by=sort_by,
                sort_desc=sort_desc
            )
        elif table_type == 'videos':
            print(f"[DEBUG] client.videos type: {type(client.videos)}, value: {client.videos}")
            try:
                response = client.videos.fetch(
                    device_id=device_id,
                    limit=limit,
                    next_token=next_token,
                    sort_by=sort_by,
                    sort_desc=sort_desc
                )
                print(f"[DEBUG] client.videos.fetch response: {response}")
            except Exception as fetch_exc:
                print(f"[ERROR] Exception in client.videos.fetch: {fetch_exc}")
                raise
        elif table_type == 'environment':
            response = client.environment.fetch(
                device_id=device_id,
                limit=limit,
                next_token=next_token,
                sort_by=sort_by,
                sort_desc=sort_desc
            )
        else:
            return {'items': [], 'next_token': None}
        
        # Extract the list of items and next_token from the response
        items = response.get('items', [])
        next_token = response.get('next_token', None)
        
        # Add formatted timestamp to each item
        for item in items:
            if 'timestamp' in item:
                try:
                    # Assuming ISO 8601 format
                    timestamp = datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00'))
                    # Format timestamp for display
                    item['formatted_time'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError) as e:
                    print(f"Error formatting timestamp {item.get('timestamp')}: {str(e)}")
                    item['formatted_time'] = item.get('timestamp', '')
        
        return {'items': items, 'next_token': next_token}
    except Exception as e:
        print(f"Error fetching {table_type} data: {str(e)}")
        return {'items': [], 'next_token': None}

def get_field_names(items: List[Dict]) -> List[str]:
    """Extract field names from the first item in a list"""
    if not items:
        return []
    # Get all keys from the first item
    return list(items[0].keys()) if items else []

def _get_device_ids():
    """Extract device ID strings from client.get_devices(), handling tuple responses."""
    try:
        devices_tuple = client.get_devices()
        devices = devices_tuple[0] if isinstance(devices_tuple, tuple) else devices_tuple
        if devices and isinstance(devices, list):
            return [d['device_id'] if isinstance(d, dict) and 'device_id' in d else d for d in devices]
        return []
    except Exception:
        return []


@app.route('/health')
def health_check():
    """Enhanced health check endpoint for AWS App Runner

    This endpoint provides basic diagnostic information and doesn't depend on
    external API connectivity to succeed, ensuring the container health check passes.
    """
    # Check environment variables without exposing sensitive values
    env_status = {
        "FLASK_APP": os.getenv("FLASK_APP", "Not set"),
        "FLASK_ENV": os.getenv("FLASK_ENV", "Not set"),
        "API_BASE_URL": os.getenv("API_BASE_URL", "Not set"),
        "SENSING_GARDEN_API_KEY": "Present" if os.getenv("SENSING_GARDEN_API_KEY") else "Not set"
    }
    
    # Always return healthy status for health checks
    # This ensures App Runner health checks pass regardless of API connectivity
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "environment": env_status,
        "message": "Health check endpoint is operational"
    }), 200

@app.route('/')
def index():
    device_ids = _get_device_ids()
    return render_template('index.html', device_ids=device_ids)


@app.route('/view_device/<device_id>')
def view_device(device_id):
    """View device content with pagination"""
    # Get pagination token from request if available
    next_token = request.args.get('next_token', None)
    prev_token = request.args.get('prev_token', None)
    
    # Track page tokens for Previous button
    token_history = request.args.get('token_history', '')
    
    try:
        classifications_count = str(client.classifications.count(device_id=device_id))
        videos_count = str(client.videos.count(device_id=device_id))
        try:
            detections_count = str(client.detections.count(device_id=device_id))
        except AttributeError:
            detections_count = "0"
        try:
            environment_count = str(client.environment.count(device_id=device_id))
        except AttributeError:
            environment_count = "0"

        classification_response = client.classifications.fetch(
            device_id=device_id,
            limit=50,
            next_token=next_token
        )
        classification_fields = []
        if classification_response.get('items'):
            classification_fields = list(classification_response['items'][0].keys())

        return render_template(
            'device_content.html',
            device_id=device_id,
            classifications=classification_response['items'],
            classification_fields=classification_fields,
            next_token=classification_response.get('next_token'),
            prev_token=prev_token,
            token_history=token_history,
            classifications_count=classifications_count,
            videos_count=videos_count,
            detections_count=detections_count,
            environment_count=environment_count,
        )
    except Exception as e:
        return render_template('error.html', error=str(e))


@app.route('/view_device/<device_id>/classifications')
def view_device_classifications(device_id):
    # Get pagination token from request if available
    next_token = request.args.get('next_token', None)
    prev_token = request.args.get('prev_token', None)
    
    # Track page tokens for Previous button
    token_history = request.args.get('token_history', '')
    current_page = int(request.args.get('page', '1'))
    
    # Process token history
    token_list = token_history.split(',') if token_history else []
    
    # Get sort parameters - default to timestamp descending
    sort_by = request.args.get('sort_by')
    sort_desc_param = request.args.get('sort_desc')
    if sort_by is None:
        sort_by = 'timestamp'
    if sort_desc_param is None:
        sort_desc = True
    else:
        sort_desc = sort_desc_param.lower() == 'true'

    # Get limit parameter with a maximum of 500 items per page
    try:
        limit = int(request.args.get('limit', '50'))
    except ValueError:
        limit = 50
    if limit < 1:
        limit = 1
    elif limit > 500:
        limit = 500
    
    # Fetch classification content for the selected device with pagination and sorting
    result = fetch_data(
        'classifications',
        device_id=device_id,
        next_token=next_token,
        sort_by=sort_by,
        sort_desc=sort_desc,
        limit=limit,
    )
    print(f"Fetched classifications for device {device_id}, next_token: {next_token}, page: {current_page}, sort_by: {sort_by}, sort_desc: {sort_desc}")
    
    # If we got empty results but we're using a next_token, try without the token
    # This handles the case where the token might be expired or invalid
    if not result['items'] and next_token and current_page > 1:
        print(f"No items found with token, trying without token for page {current_page}")
        result = fetch_data(
            'classifications',
            device_id=device_id,
            sort_by=sort_by,
            sort_desc=sort_desc,
            limit=limit,
        )
    
    # Get field names directly from the data
    fields = get_field_names(result['items'])
    if 'formatted_time' not in fields and 'timestamp' in fields:
        fields.append('formatted_time')  # Add formatted_time for display purposes
    if 'formatted_time' not in fields and 'timestamp' in fields:
        fields.append('formatted_time')  # Add formatted_time for display purposes
    
    # Update token history if moving forward and we have items
    if next_token and next_token not in token_list and result['items']:
        if current_page > len(token_list):
            token_list.append(next_token)
    
    # Get previous token (if we're not on the first page)
    prev_url = None
    if current_page > 1:
        if current_page == 2:  # Going back to first page
            prev_url = url_for(
                'view_device_classifications',
                device_id=device_id,
                page=1,
                sort_by=sort_by,
                sort_desc=str(sort_desc).lower(),
                limit=limit,
            )
        else:  # Going back to previous page
            # More robust previous token logic
            if current_page > 2 and len(token_list) >= current_page - 2:
                prev_token = token_list[current_page - 3]
                prev_url = url_for(
                    'view_device_classifications',
                    device_id=device_id,
                    next_token=prev_token,
                    token_history=','.join(token_list[: current_page - 2]),
                    page=current_page - 1,
                    sort_by=sort_by,
                    sort_desc=str(sort_desc).lower(),
                    limit=limit,
                )
            else:
                # Fallback to page 1 if we can't determine the exact previous token
                prev_url = url_for(
                    'view_device_classifications',
                    device_id=device_id,
                    page=1,
                    sort_by=sort_by,
                    sort_desc=str(sort_desc).lower(),
                    limit=limit,
                )
    
    # Generate pagination URLs
    next_page_token = result['next_token']
    pagination = {
        'has_next': next_page_token is not None,
        'next_url': url_for(
            'view_device_classifications',
            device_id=device_id,
            next_token=next_page_token,
            token_history=','.join(token_list),
            page=current_page + 1,
            sort_by=sort_by,
            sort_desc=str(sort_desc).lower(),
            limit=limit,
        )
        if next_page_token
        else None,
        'has_prev': current_page > 1,
        'prev_url': prev_url
    }
    
    return render_template(
        'device_classifications.html',
        device_id=device_id,
        classifications=result['items'],
        fields=fields,
        pagination=pagination,
        current_sort_by=sort_by,
        current_sort_desc=sort_desc,
        limit=limit,
    )

@app.route('/view_table/<table_type>')
def view_table(table_type):
    """Generic route handler for viewing any table with pagination and sorting"""
    if table_type not in ['classifications', 'models']:
        return redirect(url_for('index'))

    # For classifications, redirect to device-specific view
    if table_type == 'classifications':
        device_id = request.args.get('device_id')
        if not device_id:
            return redirect(url_for('index'))
        return redirect(url_for(f'view_device_{table_type}', device_id=device_id))
    
    # For models, handle directly
    try:
        # Fetch models with pagination and sorting
        sort_by = request.args.get('sort_by')
        sort_desc = request.args.get('sort_desc', 'false') == 'true'
        models_response = client.models.fetch(
            limit=50,
            next_token=request.args.get('next_token'),
            sort_by=sort_by,
            sort_desc=sort_desc
        )
        
        # Handle the case where there are no models
        if not models_response.get('items'):
            return render_template('models.html',
                                  models=[],
                                  field_names=[],
                                  next_token=None,
                                  prev_token=None,
                                  token_history='')
        
        # Get field names from the first model
        field_names = list(models_response['items'][0].keys())
        
        # Get sort parameters for template
        sort_by = request.args.get('sort_by')
        sort_desc = request.args.get('sort_desc', 'false') == 'true'
        
        return render_template('models.html',
                              models=models_response['items'],
                              field_names=field_names,
                              next_token=models_response.get('next_token'),
                              prev_token=request.args.get('prev_token'),
                              token_history=request.args.get('token_history', ''),
                              sort_by=sort_by,
                              sort_desc=sort_desc)
    except Exception as e:
        print(f"Error in view_table: {e}")
        return render_template('models.html',
                              models=[],
                              field_names=[],
                              next_token=None,
                              prev_token=None,
                              token_history='',
                              error=str(e))

@app.route('/item/<table_type>/<timestamp>')
def view_item(table_type, timestamp):
    """View individual item details"""
    try:
        # Try to fetch the individual item
        if table_type == 'models':
            item = client.models.get(timestamp)
        elif table_type == 'classifications':
            device_id = request.args.get('device_id')
            if not device_id:
                return jsonify({'error': 'device_id is required for classifications'}), 400
            item = client.classifications.get(device_id, timestamp)
        else:
            return jsonify({'error': 'Invalid table type'}), 404
        
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        # Get field names directly from the item
        fields = list(item.keys())
        
        return render_template('item_detail.html', 
                               item=item, 
                               table_name=table_type,
                               fields=fields,
                               json_item=json.dumps(item, indent=2))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/view_device/<device_id>/environment')
def view_device_environment(device_id):
    """View environmental data for a device with pagination and sorting"""
    # Get pagination token from request if available
    next_token = request.args.get('next_token', None)
    prev_token = request.args.get('prev_token', None)
    
    # Track page tokens for Previous button
    token_history = request.args.get('token_history', '')
    current_page = int(request.args.get('page', '1'))
    
    # Process token history
    token_list = token_history.split(',') if token_history else []
    
    # Get sort parameters - default to timestamp descending
    sort_by = request.args.get('sort_by')
    sort_desc_param = request.args.get('sort_desc')
    if sort_by is None:
        sort_by = 'timestamp'
    if sort_desc_param is None:
        sort_desc = True
    else:
        sort_desc = sort_desc_param.lower() == 'true'

    # Get limit parameter with a maximum of 500 items per page
    try:
        limit = int(request.args.get('limit', '50'))
    except ValueError:
        limit = 50
    if limit < 1:
        limit = 1
    elif limit > 500:
        limit = 500
    
    # Fetch environment data for the selected device with pagination and sorting
    result = fetch_data(
        'environment',
        device_id=device_id,
        next_token=next_token,
        sort_by=sort_by,
        sort_desc=sort_desc,
        limit=limit,
    )
    print(f"Fetched environment data for device {device_id}, next_token: {next_token}, page: {current_page}, sort_by: {sort_by}, sort_desc: {sort_desc}")
    
    # Get field names directly from the data
    fields = get_field_names(result['items'])
    if 'formatted_time' not in fields and 'timestamp' in fields:
        fields.append('formatted_time')  # Add formatted_time for display purposes
    
    # Update token history if moving forward and we have items
    if next_token and next_token not in token_list and result['items']:
        if current_page > len(token_list):
            token_list.append(next_token)
    
    # Generate pagination URLs
    next_page_token = result['next_token']
    pagination = {
        'has_next': next_page_token is not None,
        'next_url': url_for(
            'view_device_environment',
            device_id=device_id,
            next_token=next_page_token,
            token_history=','.join(token_list),
            page=current_page + 1,
            sort_by=sort_by,
            sort_desc=str(sort_desc).lower(),
            limit=limit,
        )
        if next_page_token
        else None,
        'has_prev': current_page > 1,
        'prev_url': url_for(
            'view_device_environment',
            device_id=device_id,
            page=1,
            sort_by=sort_by,
            sort_desc=str(sort_desc).lower(),
            limit=limit,
        ) if current_page > 1 else None
    }
    
    return render_template(
        'device_classifications.html',  # Reuse the same template as classifications
        device_id=device_id,
        classifications=result['items'],  # Use same variable name for template compatibility
        fields=fields,
        pagination=pagination,
        current_sort_by=sort_by,
        current_sort_desc=sort_desc,
        limit=limit,
        table_name='environment'  # Pass table name for template customization
    )

@app.route('/download_filtered/<table_type>')
def download_filtered_csv(table_type):
    """Download table data as CSV with date range filtering using backend export API"""
    try:
        # Get filter parameters
        device_id = request.args.get('device_id')
        start_time = request.args.get('start_time')
        end_time = request.args.get('end_time')
        
        # Validate required parameters
        if not device_id:
            return jsonify({'error': 'device_id is required'}), 400
        if not start_time:
            return jsonify({'error': 'start_time is required'}), 400
        if not end_time:
            return jsonify({'error': 'end_time is required'}), 400
            
        # Validate table type
        valid_tables = ['classifications', 'environment', 'videos', 'detections']
        if table_type not in valid_tables:
            return jsonify({'error': f'Invalid table type. Must be one of: {valid_tables}'}), 400
        
        # Convert dates to ISO format if needed
        try:
            # Parse and reformat dates to ensure ISO 8601 format
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            start_time_iso = start_dt.isoformat()
            end_time_iso = end_dt.isoformat()
        except ValueError as e:
            return jsonify({'error': f'Invalid date format: {str(e)}'}), 400
        
        # Validate date range - start date must be before end date
        if start_dt >= end_dt:
            return jsonify({'error': 'Start date must be before end date'}), 400
        
        # Validate reasonable date range (prevent extremely large ranges)
        date_diff = (end_dt - start_dt).days
        if date_diff > 365:
            return jsonify({'error': 'Date range cannot exceed 365 days'}), 400
        
        # Validate dates are not in the future (with small buffer for clock skew)
        from datetime import timezone, timedelta
        now = datetime.now(timezone.utc)
        # Allow up to 1 hour in the future to account for timezone/clock differences
        future_threshold = now + timedelta(hours=1)
        if end_dt > future_threshold:
            return jsonify({'error': 'End date cannot be in the future'}), 400
        
        # Call the backend export API directly
        import requests
        base_url = os.getenv('API_BASE_URL')
        api_key = os.getenv('SENSING_GARDEN_API_KEY')
        
        if not base_url or not api_key:
            return jsonify({'error': 'API configuration not found'}), 500
            
        # Prepare export request parameters
        params = {
            'table': table_type,
            'start_time': start_time_iso,
            'end_time': end_time_iso,
            'device_id': device_id,
            'filename': f'{table_type}_{device_id}_{start_dt.strftime("%Y%m%d")}_{end_dt.strftime("%Y%m%d")}.csv'
        }
        
        headers = {
            'X-API-Key': api_key
        }
        
        # Make request to backend export API
        export_url = f'{base_url.rstrip("/")}/export'
        response = requests.get(export_url, params=params, headers=headers, timeout=30)
        
        if response.status_code != 200:
            error_msg = f'Export API returned status {response.status_code}'
            try:
                error_detail = response.json().get('error', 'Unknown error')
                error_msg += f': {error_detail}'
            except:
                pass
            return jsonify({'error': error_msg}), response.status_code
        
        # Return the CSV response from backend
        csv_response = make_response(response.content)
        csv_response.headers['Content-Type'] = 'text/csv'
        csv_response.headers['Content-Disposition'] = response.headers.get('Content-Disposition', 
                                                                           f'attachment; filename={params["filename"]}')
        return csv_response
        
    except requests.RequestException as e:
        return jsonify({'error': f'Failed to connect to export API: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<table_type>')
def download_csv(table_type):
    """Download table data as CSV"""
    try:
        # Fetch all data without pagination
        if table_type == 'classifications':
            device_id = request.args.get('device_id')
            if not device_id:
                return jsonify({'error': 'device_id is required for classifications'}), 400
            response = client.classifications.fetch(
                device_id=device_id,
                limit=1000  # Fetch more data for download
            )
        elif table_type == 'models':
            response = client.models.fetch(
                limit=1000  # Fetch more data for download
            )
        elif table_type == 'videos':
            device_id = request.args.get('device_id')
            if not device_id:
                return jsonify({'error': 'device_id is required for videos'}), 400
            response = client.videos.fetch(
                device_id=device_id,
                limit=1000  # Fetch more data for download
            )
        elif table_type == 'environment':
            device_id = request.args.get('device_id')
            if not device_id:
                return jsonify({'error': 'device_id is required for environment'}), 400
            response = client.environment.fetch(
                device_id=device_id,
                limit=1000  # Fetch more data for download
            )
        else:
            return jsonify({'error': 'Invalid table type'}), 400
        
        items = response.get('items', [])
        if not items:
            return jsonify({'error': 'No data found'}), 404
        
        # Get field names from the first item
        field_names = list(items[0].keys())
        
        # Create CSV output
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=field_names)
        writer.writeheader()
        writer.writerows(items)
        
        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        if table_type == 'models':
            response.headers['Content-Disposition'] = f'attachment; filename=models.csv'
        else:
            response.headers['Content-Disposition'] = f'attachment; filename={table_type}_{device_id}.csv'
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/image_proxy')
def image_proxy():
    """Fetch an image from a remote URL and return it with same-origin headers."""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'url parameter required'}), 400

    # Limit proxying to S3 URLs to avoid abuse
    allowed_prefix = 'https://scl-sensing-garden-images.s3.amazonaws.com/'
    if not url.startswith(allowed_prefix):
        return jsonify({'error': 'URL not allowed'}), 400

    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return jsonify({'error': 'Failed to fetch image'}), resp.status_code
        proxy_resp = make_response(resp.content)
        content_type = resp.headers.get('Content-Type', 'image/jpeg')
        proxy_resp.headers['Content-Type'] = content_type
        # Explicitly allow the browser to use this image in canvas
        proxy_resp.headers['Access-Control-Allow-Origin'] = '*'
        return proxy_resp
    except requests.RequestException as exc:
        return jsonify({'error': str(exc)}), 500

@app.route('/add_model', methods=['GET'])
def add_model():
    """Show the form to add a new model"""
    return render_template('add_model.html')

@app.route('/add_model', methods=['POST'])
def add_model_submit():
    """Process the model addition form submission"""
    try:
        # Get form data
        model_data = {
            'model_id': request.form['model_id'],
            'name': request.form['name'],
            'version': request.form['version'],
            'description': request.form.get('description', '')
        }
        
        # Add metadata if provided
        metadata = request.form.get('metadata')
        if metadata:
            try:
                model_data['metadata'] = json.loads(metadata)
            except json.JSONDecodeError:
                return render_template('add_model.html', error="Invalid JSON format for metadata")
        
        # Create the model using the new API
        model = client.models.create(**model_data)
        
        return redirect(url_for('view_table', table_type='models'))
    except Exception as e:
        return render_template('add_model.html', error=str(e))

@app.route('/view_device/<device_id>/videos')
def view_device_videos(device_id):
    # Get pagination token from request if available
    next_token = request.args.get('next_token', None)
    prev_token = request.args.get('prev_token', None)
    
    # Track page tokens for Previous button
    token_history = request.args.get('token_history', '')
    current_page = int(request.args.get('page', '1'))
    
    # Process token history
    token_list = token_history.split(',') if token_history else []
    
    # Get sort parameters
    sort_by = request.args.get('sort_by')
    sort_desc = request.args.get('sort_desc')
    # By default, sort videos by timestamp descending unless overridden by request
    if sort_by is None:
        sort_by = 'timestamp'
    if sort_desc is None:
        sort_desc = True
    else:
        sort_desc = sort_desc.lower() == 'true'
    
    # Fetch videos content for the selected device with pagination and sorting
    result = fetch_data('videos', device_id=device_id, next_token=next_token, sort_by=sort_by, sort_desc=sort_desc)
    print(f"Fetched videos for device {device_id}, next_token: {next_token}, page: {current_page}, sort_by: {sort_by}, sort_desc: {sort_desc}")
    
    # Get field names directly from the data
    fields = get_field_names(result['items'])
    
    # Update token history if moving forward and we have items
    if next_token and next_token not in token_list and result['items']:
        if current_page > len(token_list):
            token_list.append(next_token)
    
    # Get previous token (if we're not on the first page)
    prev_url = None
    if current_page > 1:
        if current_page == 2:  # Going back to first page
            prev_url = url_for('view_device_videos', device_id=device_id, page=1)
        else:  # Going back to previous page
            prev_token = token_list[current_page-3] if current_page > 2 and len(token_list) >= current_page-2 else None
            prev_url = url_for('view_device_videos', 
                              device_id=device_id, 
                              next_token=prev_token,
                              page=current_page-1,
                              token_history=','.join(token_list[:current_page-2]))
    
    # Get next URL if we have a next token
    next_url = None
    if result['next_token']:
        next_url = url_for('view_device_videos', 
                          device_id=device_id, 
                          next_token=result['next_token'],
                          page=current_page+1,
                          token_history=','.join(token_list))
    
    # Create pagination object for template
    pagination = {
        'has_prev': prev_url is not None,
        'has_next': next_url is not None,
        'prev_url': prev_url,
        'next_url': next_url
    }
    
    # Create download URL
    download_url = url_for('download_csv', table_type='videos', device_id=device_id)
    
    return render_template('videos.html', 
                           device_id=device_id, 
                           items=result['items'],
                           fields=fields,
                           pagination=pagination,
                           current_sort_by=sort_by,
                           current_sort_desc=sort_desc,
                           download_url=download_url)

@app.route('/view_device/<device_id>/feed')
def view_device_feed(device_id):
    """Unified device feed page showing all content types chronologically"""
    try:
        print(f"[DEBUG] Starting feed page for device: {device_id}")
        
        # Get counts for display
        print("[DEBUG] Getting classifications count...")
        classifications_count = client.classifications.count(device_id=device_id)
        print(f"[DEBUG] Classifications count: {classifications_count}")
        
        print("[DEBUG] Getting videos count...")
        videos_count = client.videos.count(device_id=device_id)
        print(f"[DEBUG] Videos count: {videos_count}")
        
        print("[DEBUG] Getting detections count...")
        try:
            detections_count = client.detections.count(device_id=device_id)
            print(f"[DEBUG] Detections count: {detections_count}")
        except AttributeError:
            detections_count = 0
            print("[DEBUG] Detections count not available, using 0")
        
        print("[DEBUG] Getting environment count...")
        try:
            environment_count = client.environment.count(device_id=device_id)
            print(f"[DEBUG] Environment count: {environment_count}")
        except AttributeError:
            environment_count = 0
            print("[DEBUG] Environment count not available, using 0")
        
        print("[DEBUG] Rendering template...")
        return render_template('device_feed.html',
                               device_id=device_id,
                               classifications_count=classifications_count,
                               videos_count=videos_count,
                               detections_count=detections_count,
                               environment_count=environment_count)
    except Exception as e:
        print(f"[ERROR] Feed page error: {str(e)}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e))

@app.route('/api/device/<device_id>/feed_data')
def get_device_feed_data(device_id):
    """API endpoint for unified feed data fetching"""
    content_type = request.args.get('content_type', 'classifications')
    next_token = request.args.get('next_token')
    limit = min(int(request.args.get('limit', 20)), 100)  # Max 100 items
    sort_desc = request.args.get('sort_desc', 'true').lower() == 'true'
    
    try:
        print(f"[DEBUG] Feed API called: device_id={device_id}, content_type={content_type}, limit={limit}")
        result = fetch_data(
            content_type,
            device_id=device_id,
            next_token=next_token,
            sort_by='timestamp',
            sort_desc=sort_desc,
            limit=limit
        )
        
        # Add content type to each item
        for item in result['items']:
            item['_contentType'] = content_type
        
        print(f"[DEBUG] Successfully fetched {len(result['items'])} items for {content_type}")
        return jsonify(result)
    except Exception as e:
        print(f"[ERROR] Feed API error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'items': [], 'next_token': None}), 500

@app.route('/delete_device/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    """Delete a device and all its associated data"""
    try:
        print(f"[DEBUG] Starting device deletion for device: {device_id}")
        
        # Call the client's delete_device method
        result = client.delete_device(device_id)
        print(f"[DEBUG] Delete result: {result}")
        
        # Check if deletion was successful
        if result.get('statusCode') == 200:
            return jsonify({
                'success': True,
                'message': result.get('message', 'Device deleted successfully')
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Failed to delete device')
            }), 400
            
    except Exception as e:
        print(f"[ERROR] Device deletion error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin')
def admin():
    """Admin dashboard for data oversight."""
    device_ids = _get_device_ids()
    return render_template('admin.html', device_ids=device_ids)

@app.route('/api/admin/device-summary')
def admin_device_summary():
    """Get summary stats for all devices."""
    device_ids = _get_device_ids()
    devices = {}
    for did in device_ids:
        try:
            total = client.videos.count(device_id=did)
            oldest_ts = None
            newest_ts = None
            try:
                oldest_resp = client.videos.fetch(device_id=did, limit=1, sort_desc=False)
                if oldest_resp.get('items'):
                    oldest_ts = oldest_resp['items'][0].get('timestamp')
            except Exception:
                pass
            try:
                newest_resp = client.videos.fetch(device_id=did, limit=1, sort_desc=True)
                if newest_resp.get('items'):
                    newest_ts = newest_resp['items'][0].get('timestamp')
            except Exception:
                pass
            devices[did] = {
                'total_videos': total,
                'oldest_timestamp': oldest_ts,
                'newest_timestamp': newest_ts,
            }
        except Exception as e:
            devices[did] = {'error': str(e)}
    return jsonify({'devices': devices})

@app.route('/api/admin/video-counts')
def admin_video_counts():
    """Get video counts per day for a device (or all devices)."""
    device_id = request.args.get('device_id')
    device_ids = [device_id] if device_id else _get_device_ids()
    result = {}
    for did in device_ids:
        counts = defaultdict(int)
        next_token = None
        while True:
            try:
                resp = client.videos.fetch(device_id=did, limit=500, next_token=next_token, sort_desc=True)
                for item in resp.get('items', []):
                    ts = item.get('timestamp', '')
                    date = ts[:10] if len(ts) >= 10 else 'unknown'
                    counts[date] += 1
                next_token = resp.get('next_token')
                if not next_token:
                    break
            except Exception as e:
                print(f"Error fetching videos for {did}: {e}")
                break
        result[did] = dict(sorted(counts.items()))
    return jsonify(result)

@app.route('/api/admin/s3-orphans')
def admin_s3_orphans():
    """Scan S3 for video files not registered in DynamoDB."""
    try:
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_REGION', 'us-east-1'),
        )
        dynamodb = boto3.resource(
            'dynamodb',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_REGION', 'us-east-1'),
        )
        table = dynamodb.Table('sensing-garden-videos')
        bucket = 'scl-sensing-garden-videos'

        # List all .mp4 files under videos/ prefix
        s3_files = []
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix='videos/'):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key.endswith('.mp4'):
                    s3_files.append({
                        'key': key,
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat(),
                    })

        # Scan DynamoDB for all known video keys and compare directly
        db_keys = set()
        scan_kwargs = {'ProjectionExpression': 'video_key'}
        try:
            while True:
                response = table.scan(**scan_kwargs)
                for item in response.get('Items', []):
                    if 'video_key' in item:
                        db_keys.add(item['video_key'])
                if 'LastEvaluatedKey' not in response:
                    break
                scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        except Exception as e:
            print(f"Error scanning DynamoDB: {e}")
            return jsonify({'error': f'DynamoDB scan failed: {e}'}), 500

        orphans = [f for f in s3_files if f['key'] not in db_keys]

        return jsonify({
            'total_s3_files': len(s3_files),
            'orphan_count': len(orphans),
            'orphans': orphans[:500],  # Limit response size
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/s3-presign')
def admin_s3_presign():
    """Generate a presigned URL for an S3 video key."""
    key = request.args.get('key')
    if not key:
        return jsonify({'error': 'key parameter required'}), 400
    if not key.startswith('videos/') or not key.endswith('.mp4'):
        return jsonify({'error': 'Invalid key'}), 400
    try:
        s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_REGION', 'us-east-1'),
        )
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': 'scl-sensing-garden-videos', 'Key': key},
            ExpiresIn=3600,
        )
        return jsonify({'url': url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
