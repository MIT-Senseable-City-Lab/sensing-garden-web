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
        else:
            return {'items': [], 'next_token': None}
        
        # Extract the list of items and next_token from the response
        items = response.get('items', [])
        next_token = response.get('next_token', None)
        
        # Add formatted timestamp to each item in a human friendly form
        for item in items:
            if 'timestamp' in item:
                try:
                    timestamp = datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00'))
                    # Example format: "May 21, 2024 01:23:45 PM"
                    item['formatted_time'] = timestamp.strftime('%b %d, %Y %I:%M:%S %p')
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
    try:
        devices_tuple = client.get_devices()
        print('DEBUG: client.get_devices() returned:', devices_tuple)
        devices = devices_tuple[0] if isinstance(devices_tuple, tuple) else devices_tuple
        # If get_devices() returns a list of dicts with 'device_id', extract them
        if devices and isinstance(devices, list):
            device_ids = [d['device_id'] if isinstance(d, dict) and 'device_id' in d else d for d in devices]
        else:
            device_ids = []
    except Exception as e:
        device_ids = []
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

if __name__ == '__main__':
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
