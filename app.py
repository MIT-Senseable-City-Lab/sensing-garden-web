import io
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import boto3
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

# Create S3 client for generating presigned URLs locally
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

def fix_presigned_url(broken_url: str) -> str:
    """
    Fix broken presigned URLs by regenerating them with local credentials.

    Args:
        broken_url: The broken presigned URL from the backend

    Returns:
        A working presigned URL generated with local credentials
    """
    if not broken_url:
        return broken_url

    try:
        # Extract S3 bucket and key from the broken URL
        # URLs have format: https://bucket-name.s3.amazonaws.com/key?params
        match = re.search(r'https://([^.]+)\.s3\.amazonaws\.com/(.+?)\?', broken_url)
        if not match:
            # Fallback pattern for different URL formats
            match = re.search(r'amazonaws\.com/(.+?)\?', broken_url)
            if match:
                s3_key = match.group(1)
                # Determine bucket based on the key pattern
                if s3_key.startswith('videos/'):
                    bucket_name = 'scl-sensing-garden-videos'
                elif s3_key.startswith('classification/') or s3_key.startswith('detection/'):
                    bucket_name = 'scl-sensing-garden-images'
                else:
                    print(f"Could not determine bucket for key: {s3_key}")
                    return broken_url
            else:
                print(f"Could not parse URL: {broken_url}")
                return broken_url
        else:
            bucket_name = match.group(1)
            s3_key = match.group(2)

        # Generate a new presigned URL with local credentials
        working_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600  # 1 hour expiration
        )

        print(f"Fixed presigned URL: {broken_url[:100]}... -> {working_url[:100]}...")
        return working_url

    except Exception as e:
        print(f"Error fixing presigned URL {broken_url}: {e}")
        return broken_url

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
        
        # Add formatted timestamp and fix video URLs
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

            # Fix broken presigned URLs for videos and images
            if 'video_url' in item and item['video_url']:
                item['video_url'] = fix_presigned_url(item['video_url'])
            if 'image_url' in item and item['image_url']:
                item['image_url'] = fix_presigned_url(item['image_url'])
        
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

@app.route('/sidara/load-more-videos')
def sidara_load_more_videos():
    """Load more videos for pagination"""
    try:
        device_id = request.args.get('device_id')
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 30))

        if not device_id:
            return jsonify({'error': 'device_id required'}), 400

        videos_response = client.videos.fetch(
            device_id=device_id,
            limit=limit,
            offset=offset,
            sort_by='timestamp',
            sort_desc=True
        )

        device_videos = videos_response.get('items', [])
        processed_videos = []

        for video in device_videos:
            # Fix video URLs before processing
            video_url = fix_presigned_url(video.get('video_url', ''))
            thumbnail_url = fix_presigned_url(video.get('thumbnail_url', '') or video.get('video_url', ''))

            video_entry = {
                'device_id': device_id,
                'video_id': f"{device_id}_{video.get('timestamp', 'unknown')}",
                'video_url': video_url,
                'timestamp': video.get('timestamp'),
                'formatted_time': video.get('formatted_time'),
                'duration': video.get('duration', 0),
                'metadata': video.get('metadata', {}),
                'thumbnail_url': thumbnail_url
            }
            processed_videos.append(video_entry)

        return jsonify({
            'videos': processed_videos,
            'count': len(processed_videos)
        })

    except Exception as e:
        print(f"Error loading more videos: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/video_frame_proxy')
def video_frame_proxy():
    """Generate a poster frame/thumbnail from a video URL using FFmpeg or similar."""
    video_url = request.args.get('url')
    if not video_url:
        return jsonify({'error': 'url parameter required'}), 400

    # Limit to S3 video URLs for security
    allowed_prefixes = [
        'https://scl-sensing-garden-videos.s3.amazonaws.com/',
        'https://scl-sensing-garden-images.s3.amazonaws.com/'
    ]
    if not any(video_url.startswith(prefix) for prefix in allowed_prefixes):
        return jsonify({'error': 'URL not allowed'}), 400

    try:
        import subprocess
        import tempfile
        import base64

        # Check if ffmpeg is available
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, timeout=5)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            # FFmpeg not available, return error
            return jsonify({'error': 'Video processing not available'}), 503

        # Create temporary file for thumbnail
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            # Extract first frame using FFmpeg with timeout
            cmd = [
                'ffmpeg', '-i', video_url, '-ss', '00:00:01', '-vframes', '1',
                '-q:v', '2', '-f', 'image2', temp_path, '-y'
            ]

            result = subprocess.run(cmd, capture_output=True, timeout=15)

            if result.returncode == 0:
                # Read the generated thumbnail
                with open(temp_path, 'rb') as f:
                    thumbnail_data = f.read()

                # Clean up temp file
                os.unlink(temp_path)

                # Return thumbnail as response
                response = make_response(thumbnail_data)
                response.headers['Content-Type'] = 'image/jpeg'
                response.headers['Access-Control-Allow-Origin'] = '*'
                response.headers['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour
                return response
            else:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                return jsonify({'error': 'Failed to extract video frame'}), 500

        except subprocess.TimeoutExpired:
            # Clean up temp file on timeout
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return jsonify({'error': 'Video processing timeout'}), 504

    except Exception as e:
        return jsonify({'error': f'Video processing failed: {str(e)}'}), 500

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
    
    return render_template('videos.html',
                           device_id=device_id,
                           items=result['items'],
                           fields=fields,
                           pagination=pagination,
                           current_sort_by=sort_by,
                           current_sort_desc=sort_desc)

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

# Sidara device configuration
SIDARA_DEVICES = [
    "b8f2ed92a70e5df3",
    "e73325dab87ec077",
    "d590bf3c30b2cf25"
]

def parse_sidara_timestamp(timestamp_str):
    """Parse Sidara timestamp format like '2025-04-28T13-39-10-380729_0229'"""
    try:
        # Handle standard ISO format first
        if 'T' in timestamp_str and ':' in timestamp_str:
            if timestamp_str.endswith('Z'):
                return datetime.fromisoformat(timestamp_str[:-1] + '+00:00')
            else:
                return datetime.fromisoformat(timestamp_str)

        # Handle Sidara custom format: 2025-04-28T13-39-10-380729_0229
        if 'T' in timestamp_str and '-' in timestamp_str.split('T')[1]:
            date_part, time_part = timestamp_str.split('T')
            # Split time part and remove frame number if present
            if '_' in time_part:
                time_part = time_part.split('_')[0]

            # Replace hyphens with colons in time part: 13-39-10-380729 -> 13:39:10.380729
            time_components = time_part.split('-')
            if len(time_components) >= 3:
                hours = time_components[0]
                minutes = time_components[1]
                seconds = time_components[2]
                microseconds = time_components[3] if len(time_components) > 3 else '0'

                # Format as standard timestamp
                formatted_time = f"{hours}:{minutes}:{seconds}.{microseconds}"
                iso_timestamp = f"{date_part}T{formatted_time}"
                return datetime.fromisoformat(iso_timestamp)

        # Fallback
        return datetime.fromisoformat(timestamp_str)

    except Exception as e:
        print(f"Warning: Could not parse timestamp {timestamp_str}: {e}")
        return None

def apply_false_positive_filtering(classifications, confidence_threshold=0.05, species_spacing_minutes=5, detection_rate_limit=5.0, session_min_duration=5):
    """Apply sophisticated false positive filtering based on the analysis methodology with configurable parameters"""
    if not classifications:
        return []

    filtered = []
    from datetime import datetime
    import collections

    # 1. Confidence Score Filtering (configurable threshold)
    confidence_filtered = [item for item in classifications if item.get('species_confidence', item.get('confidence', 0)) >= confidence_threshold]

    # 2. Temporal Pattern Analysis - detect and filter burst/testing patterns
    timestamps = []
    for item in confidence_filtered:
        timestamp = item.get('timestamp')
        if timestamp:
            dt = parse_sidara_timestamp(timestamp)
            if dt:
                timestamps.append((dt, item))

    # Sort by timestamp
    timestamps.sort(key=lambda x: x[0])

    # 3. Session-Based Filtering - identify sustained vs. calibration sessions
    session_groups = []
    current_session = []

    for i, (dt, item) in enumerate(timestamps):
        if i == 0:
            current_session = [item]
        else:
            prev_dt = timestamps[i-1][0]
            time_diff = (dt - prev_dt).total_seconds() / 60  # minutes

            # If gap > 60 minutes, start new session
            if time_diff > 60:
                if len(current_session) > 0:
                    session_groups.append(current_session)
                current_session = [item]
            else:
                current_session.append(item)

    if current_session:
        session_groups.append(current_session)

    # 4. Filter sessions - only include sustained periods (configurable minimum duration)
    for session in session_groups:
        if len(session) >= 3:  # At least 3 detections in session
            # Check for burst patterns (many detections in short time)
            session_timestamps = []
            for item in session:
                timestamp = item.get('timestamp')
                if timestamp:
                    dt = parse_sidara_timestamp(timestamp)
                    if dt:
                        session_timestamps.append(dt)

            if len(session_timestamps) >= 2:
                session_duration = (max(session_timestamps) - min(session_timestamps)).total_seconds() / 60
                detection_rate = len(session) / session_duration if session_duration > 0 else float('inf')

                # Filter sessions based on configurable criteria
                if detection_rate <= detection_rate_limit and session_duration >= session_min_duration:
                    filtered.extend(session)

    # 5. Species-specific burst filtering - remove repetitive species in short timeframes (configurable spacing)
    final_filtered = []
    species_timestamps = collections.defaultdict(list)

    for item in filtered:
        species = item.get('species', item.get('predicted_class', 'Unknown'))
        timestamp = item.get('timestamp')
        if timestamp:
            dt = parse_sidara_timestamp(timestamp)
            if dt:
                species_timestamps[species].append((dt, item))

    # For each species, filter out rapid repeats based on configurable spacing
    for species, detections in species_timestamps.items():
        detections.sort(key=lambda x: x[0])

        # Only include if there's reasonable spacing between detections of same species
        for i, (dt, item) in enumerate(detections):
            if i == 0:
                final_filtered.append(item)
            else:
                prev_dt = detections[i-1][0]
                time_diff = (dt - prev_dt).total_seconds() / 60

                # Only include if spacing is greater than the configured threshold
                if time_diff > species_spacing_minutes:
                    final_filtered.append(item)

    return final_filtered

@app.route('/sidara')
def sidara_analysis():
    """Interactive video categorization interface for Sidara devices"""
    print("=== SIDARA ROUTE ACCESSED ===", flush=True)
    try:
        # Initialize video data structure
        video_data = {
            'videos': [],
            'total_videos': 0,
            'devices': SIDARA_DEVICES
        }

        # Fetch video data from all three Sidara devices
        for device_id in SIDARA_DEVICES:
            print(f"Fetching videos for device: {device_id}", flush=True)

            try:
                # Get video count for this device
                videos_count = client.videos.count(device_id=device_id)
                print(f"Device {device_id} has {videos_count} videos", flush=True)

                if videos_count > 0:
                    # Fetch only first batch of videos for faster initial load
                    videos_response = client.videos.fetch(
                        device_id=device_id,
                        limit=30,  # Reduced for much faster initial load
                        sort_by='timestamp',
                        sort_desc=True
                    )

                    device_videos = videos_response.get('items', [])
                    print(f"Retrieved {len(device_videos)} videos for device {device_id}", flush=True)

                    # Process each video and add device info
                    for video in device_videos:
                        # Fix video URLs before processing
                        video_url = fix_presigned_url(video.get('video_url', ''))
                        thumbnail_url = fix_presigned_url(video.get('thumbnail_url', '') or video.get('video_url', ''))

                        video_entry = {
                            'device_id': device_id,
                            'video_id': f"{device_id}_{video.get('timestamp', 'unknown')}",
                            'video_url': video_url,
                            'timestamp': video.get('timestamp'),
                            'formatted_time': video.get('formatted_time'),
                            'duration': video.get('duration', 0),  # Duration in seconds if available
                            'metadata': video.get('metadata', {}),
                            # We'll extract these in the frontend from video_url for thumbnails
                            'thumbnail_url': thumbnail_url
                        }
                        video_data['videos'].append(video_entry)

                video_data['total_videos'] += videos_count

            except Exception as e:
                print(f"Error fetching videos for device {device_id}: {str(e)}", flush=True)
                continue

        # Sort all videos by timestamp (newest first)
        video_data['videos'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)

        # Add metadata for pagination
        video_data['displayed_videos'] = len(video_data['videos'])
        video_data['initial_batch_size'] = 30

        print(f"Sidara video categorization ready: {len(video_data['videos'])} videos loaded (of {video_data['total_videos']} total) from {len(SIDARA_DEVICES)} devices", flush=True)

        return render_template('sidara.html', data=video_data)

    except Exception as e:
        print(f"Error in Sidara video interface: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e))

@app.route('/species/<species_name>')
def species_detail(species_name):
    """Detailed view of all detections for a specific species using live data"""
    try:
        species_data = {
            'species_name': species_name,
            'all_detections': [],
            'total_detections': 0,
            'confidence_stats': {},
            'temporal_distribution': {},
            'device_breakdown': {}
        }

        # Collect all detections for this species across all Sidara devices
        for device_id in SIDARA_DEVICES:
            try:
                classifications_count = client.classifications.count(device_id=device_id)

                if classifications_count > 0:
                    print(f"Fetching species data for {species_name} from device {device_id}")

                    # Fetch classifications for this device
                    classifications_response = client.classifications.fetch(
                        device_id=device_id,
                        limit=1000,  # Get comprehensive data for species detail view
                        sort_by='timestamp',
                        sort_desc=True
                    )

                    device_classifications = classifications_response.get('items', [])

                    # Apply false positive filtering with relaxed parameters
                    filtered_classifications = apply_false_positive_filtering(
                        device_classifications,
                        confidence_threshold=0.03,  # Lower threshold
                        species_spacing_minutes=1,  # Much shorter spacing
                        detection_rate_limit=50.0,  # Even higher rate limit to include busy sessions
                        session_min_duration=1      # Shorter minimum duration
                    )

                    # Filter for specific species with case-insensitive matching
                    species_detections = [
                        item for item in filtered_classifications
                        if item.get('species', item.get('predicted_class', '')).lower() == species_name.lower()
                        and item.get('species_confidence', item.get('confidence', 0)) >= 0.05
                    ]

                    print(f"Found {len(species_detections)} detections of {species_name} from device {device_id}")

                    # Process each detection
                    for item in species_detections:
                        detection = {
                            'image_url': fix_presigned_url(item.get('image_url', '')),
                            'timestamp': item.get('timestamp'),
                            'device_id': device_id,
                            'confidence': item.get('species_confidence', item.get('confidence', 0)),
                            'metadata': item.get('metadata', {}),
                            'bbox': item.get('bounding_box', item.get('bbox')),
                            'formatted_timestamp': None
                        }

                        # Format timestamp for display
                        if detection['timestamp']:
                            dt = parse_sidara_timestamp(detection['timestamp'])
                            if dt:
                                detection['formatted_timestamp'] = dt.strftime('%Y-%m-%d %H:%M:%S')

                        species_data['all_detections'].append(detection)

                    # Update device breakdown
                    if len(species_detections) > 0:
                        species_data['device_breakdown'][device_id] = {
                            'count': len(species_detections),
                            'device_name': f'Sidara Device {device_id[:8]}...'
                        }

            except Exception as e:
                print(f"Error fetching species data for device {device_id}: {str(e)}")
                continue

        # Sort all detections by confidence (highest first)
        species_data['all_detections'].sort(key=lambda x: x['confidence'], reverse=True)
        species_data['total_detections'] = len(species_data['all_detections'])

        # Calculate confidence statistics
        if species_data['all_detections']:
            confidences = [d['confidence'] for d in species_data['all_detections']]
            species_data['confidence_stats'] = {
                'min': min(confidences),
                'max': max(confidences),
                'avg': sum(confidences) / len(confidences),
                'median': sorted(confidences)[len(confidences)//2]
            }

        # Temporal distribution analysis
        temporal_counts = {}
        for detection in species_data['all_detections']:
            if detection['formatted_timestamp']:
                date_key = detection['formatted_timestamp'][:10]  # YYYY-MM-DD
                temporal_counts[date_key] = temporal_counts.get(date_key, 0) + 1

        species_data['temporal_distribution'] = dict(sorted(temporal_counts.items()))

        print(f"Species detail complete for {species_name}: {species_data['total_detections']} total detections across {len(species_data['device_breakdown'])} devices")

        return render_template('species_detail.html', data=species_data)

    except Exception as e:
        print(f"Error in species detail view: {str(e)}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e))

@app.route('/sidara/filtered-analysis', methods=['POST'])
def sidara_filtered_analysis():
    """Apply interactive filtering to live Sidara data and return results"""
    try:
        # Get filter parameters from request
        filter_params = request.get_json()
        confidence_threshold = filter_params.get('confidence_threshold', 0.15)
        species_spacing_minutes = filter_params.get('species_spacing_minutes', 5)
        detection_rate_limit = filter_params.get('detection_rate_limit', 1.0)
        session_min_duration = filter_params.get('session_min_duration', 30)

        print(f"[DEBUG] Applying filtering with params: confidence={confidence_threshold}, spacing={species_spacing_minutes}, rate={detection_rate_limit}, duration={session_min_duration}")

        # Collect all classifications from all Sidara devices
        all_classifications = []

        for device_id in SIDARA_DEVICES:
            try:
                classifications_count = client.classifications.count(device_id=device_id)

                if classifications_count > 0:
                    # Fetch all classifications for comprehensive filtering
                    classifications_response = client.classifications.fetch(
                        device_id=device_id,
                        limit=1000,  # Get comprehensive data
                        sort_by='timestamp',
                        sort_desc=True
                    )

                    device_classifications = classifications_response.get('items', [])
                    all_classifications.extend(device_classifications)

            except Exception as e:
                print(f"[ERROR] Error fetching data for device {device_id}: {str(e)}")
                continue

        print(f"[DEBUG] Total raw classifications: {len(all_classifications)}")

        # Apply filtering with custom parameters
        filtered_classifications = apply_false_positive_filtering(
            all_classifications,
            confidence_threshold=confidence_threshold,
            species_spacing_minutes=species_spacing_minutes,
            detection_rate_limit=detection_rate_limit,
            session_min_duration=session_min_duration
        )

        print(f"[DEBUG] Filtered classifications: {len(filtered_classifications)}")

        # Analyze species from filtered data
        species_summary = {}
        for item in filtered_classifications:
            species = item.get('species', item.get('predicted_class', 'Unknown'))
            confidence = item.get('species_confidence', item.get('confidence', 0))
            timestamp = item.get('timestamp')

            if species not in species_summary:
                species_summary[species] = {
                    'count': 0,
                    'avg_confidence': 0,
                    'total_confidence': 0,
                    'recent_images': []
                }

            species_summary[species]['count'] += 1
            species_summary[species]['total_confidence'] += confidence
            species_summary[species]['avg_confidence'] = (
                species_summary[species]['total_confidence'] / species_summary[species]['count']
            )

            # Add image info for preview (top 3 highest confidence per species)
            if len(species_summary[species]['recent_images']) < 3:
                if 'image_url' in item:
                    detection_data = {
                        'image_url': fix_presigned_url(item.get('image_url', '')),
                        'timestamp': timestamp,
                        'device_id': item.get('device_id', 'unknown'),
                        'confidence': confidence
                    }
                    species_summary[species]['recent_images'].append(detection_data)

        # Sort species by count
        sorted_species = sorted(
            species_summary.items(),
            key=lambda x: x[1]['count'],
            reverse=True
        )

        # Calculate statistics
        raw_count = len(all_classifications)
        filtered_count = len(filtered_classifications)
        reduction_percent = round(((raw_count - filtered_count) / raw_count * 100) if raw_count > 0 else 0, 1)
        species_count = len(species_summary)

        # Format species data for frontend
        species_data = []
        for species_name, info in sorted_species:
            species_data.append({
                'name': species_name,
                'count': info['count'],
                'avg_confidence': info['avg_confidence'],
                'recent_images': info['recent_images']
            })

        response_data = {
            'raw_count': raw_count,
            'filtered_count': filtered_count,
            'reduction_percent': reduction_percent,
            'total_species': species_count,  # Match frontend expectations
            'total_detections': filtered_count,  # Add total detections count
            'sorted_species': sorted_species,  # Match frontend expectations
            'species_data': species_data  # Keep legacy format as backup
        }

        print(f"[DEBUG] Returning response: {raw_count} -> {filtered_count} ({reduction_percent}% reduction), {species_count} species")

        return jsonify(response_data)

    except Exception as e:
        print(f"[ERROR] Error in filtered analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/debug_thumbnails.html')
def debug_thumbnails():
    """Serve the thumbnail debug page"""
    with open('debug_thumbnails.html', 'r') as f:
        content = f.read()
    return content

if __name__ == '__main__':
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
