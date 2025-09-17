#!/usr/bin/env python3
"""
Generate thumbnails for Sidara videos and upload to S3.
Creates small (~24KB) JPEG thumbnails by downloading only the first 2MB of each video.
"""

import os
import sys
import json
import time
import boto3
import cv2
from io import BytesIO
from PIL import Image
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from boto3.dynamodb.conditions import Key

# Configuration
THUMBNAIL_WIDTH = 192  # 30% of 640
THUMBNAIL_HEIGHT = 108  # 30% of 360
JPEG_QUALITY = 30  # Low quality for small file size
MAX_DOWNLOAD_SIZE = 2 * 1024 * 1024  # 2MB per video to ensure we get video metadata
CONCURRENT_WORKERS = 4  # Process 4 videos at a time
S3_BUCKET = 'scl-sensing-garden-videos'
S3_REGION = 'us-east-1'  # Most S3 buckets default to us-east-1
DYNAMODB_TABLE = 'sensing-garden-videos'  # DynamoDB table name - VERIFIED!

# Cost tracking
COST_PER_GB = 0.085  # AWS CloudFront cost per GB
total_bytes_downloaded = 0
total_thumbnails_created = 0
failed_videos = []

def setup_logging():
    """Setup colored logging similar to the web interface."""
    from colorama import init, Fore, Style
    init(autoreset=True)
    return {
        'info': lambda msg: print(f"{Fore.CYAN}ℹ️  {msg}{Style.RESET_ALL}"),
        'success': lambda msg: print(f"{Fore.GREEN}✅ {msg}{Style.RESET_ALL}"),
        'warning': lambda msg: print(f"{Fore.YELLOW}⚠️  {msg}{Style.RESET_ALL}"),
        'error': lambda msg: print(f"{Fore.RED}❌ {msg}{Style.RESET_ALL}"),
        'download': lambda msg: print(f"{Fore.BLUE}📥 {msg}{Style.RESET_ALL}"),
        'upload': lambda msg: print(f"{Fore.MAGENTA}📤 {msg}{Style.RESET_ALL}"),
        'cache': lambda msg: print(f"{Fore.GREEN}💾 {msg}{Style.RESET_ALL}"),
    }

log = setup_logging()

def get_s3_client():
    """Get authenticated S3 client."""
    return boto3.client('s3', region_name=S3_REGION)

def get_dynamodb_table():
    """Get DynamoDB table resource."""
    dynamodb = boto3.resource('dynamodb', region_name=S3_REGION)
    return dynamodb.Table(DYNAMODB_TABLE)

def list_videos_from_s3():
    """List all video files from S3 bucket."""
    log['info']("Fetching video list from S3...")
    s3 = get_s3_client()

    videos = []
    paginator = s3.get_paginator('list_objects_v2')

    # List all .mp4 files in videos/ prefix
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix='videos/'):
        if 'Contents' in page:
            for obj in page['Contents']:
                if obj['Key'].endswith('.mp4'):
                    videos.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified']
                    })

    log['success'](f"Found {len(videos)} videos in S3")
    return videos

def check_thumbnail_exists(s3_client, video_key):
    """Check if thumbnail already exists in S3."""
    thumbnail_key = video_key.replace('videos/', 'thumbnails/').replace('.mp4', '.jpg')
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=thumbnail_key)
        return True
    except:
        return False

def download_partial_video(s3_client, video_key, max_size=MAX_DOWNLOAD_SIZE):
    """Download only the first part of a video using S3 Range requests."""
    global total_bytes_downloaded

    try:
        # Use S3 GetObject with Range header to get only partial content
        response = s3_client.get_object(
            Bucket=S3_BUCKET,
            Key=video_key,
            Range=f'bytes=0-{max_size-1}'
        )

        # Read the body content
        video_bytes = response['Body'].read()
        downloaded = len(video_bytes)
        total_bytes_downloaded += downloaded

        return video_bytes, downloaded

    except s3_client.exceptions.NoSuchKey:
        log['error'](f"Video not found in S3: {video_key}")
        return None, 0
    except Exception as e:
        log['error'](f"S3 download error: {e}")
        return None, 0

def generate_thumbnail_from_bytes(video_bytes, video_key):
    """Generate a thumbnail from partial video bytes."""
    import subprocess
    try:
        # Write bytes to temporary file
        temp_video_path = f"/tmp/{video_key.split('/')[-1]}"
        temp_image_path = f"/tmp/{video_key.split('/')[-1].replace('.mp4', '.jpg')}"

        with open(temp_video_path, 'wb') as f:
            f.write(video_bytes)

        # Use ffmpeg directly to extract frame (more tolerant of partial files)
        # -ss 0 : start at beginning
        # -i : input file
        # -frames:v 1 : extract only 1 frame
        # -vf scale : resize to target dimensions
        # -q:v : JPEG quality (2-31, lower is better)
        cmd = [
            'ffmpeg',
            '-ss', '0',
            '-i', temp_video_path,
            '-frames:v', '1',
            '-vf', f'scale={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}',
            '-q:v', '15',  # Moderate quality
            '-loglevel', 'error',
            '-y',  # Overwrite output
            temp_image_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        # Clean up video file
        os.remove(temp_video_path)

        # Check if image was created
        if os.path.exists(temp_image_path) and os.path.getsize(temp_image_path) > 0:
            # Read the generated image
            with open(temp_image_path, 'rb') as f:
                thumbnail_bytes = f.read()
            os.remove(temp_image_path)

            size_kb = len(thumbnail_bytes) / 1024
            log['cache'](f"Generated thumbnail: {size_kb:.1f} KB")
            return thumbnail_bytes
        else:
            # If ffmpeg fails, fall back to OpenCV approach
            log['warning'](f"ffmpeg failed, trying OpenCV")

            # Rewrite video bytes for OpenCV attempt
            with open(temp_video_path, 'wb') as f:
                f.write(video_bytes)

            cap = cv2.VideoCapture(temp_video_path)
            ret, frame = cap.read()
            cap.release()
            os.remove(temp_video_path)

            if not ret or frame is None:
                log['error'](f"Could not extract frame from video")
                return None

            # Convert BGR to RGB (OpenCV uses BGR)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Create PIL Image and resize
        img = Image.fromarray(frame_rgb)
        img.thumbnail((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.Resampling.LANCZOS)

        # Save to bytes with JPEG compression
        output = BytesIO()
        img.save(output, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        output.seek(0)

        thumbnail_bytes = output.getvalue()
        size_kb = len(thumbnail_bytes) / 1024

        # If still too large, reduce quality further
        if size_kb > 30:
            output = BytesIO()
            img.save(output, format='JPEG', quality=20, optimize=True)
            output.seek(0)
            thumbnail_bytes = output.getvalue()
            size_kb = len(thumbnail_bytes) / 1024

        log['cache'](f"Generated thumbnail: {size_kb:.1f} KB")
        return thumbnail_bytes

    except Exception as e:
        log['error'](f"Thumbnail generation error: {e}")
        return None

def upload_thumbnail_to_s3(s3_client, thumbnail_bytes, video_key):
    """Upload thumbnail to S3."""
    thumbnail_key = video_key.replace('videos/', 'thumbnails/').replace('.mp4', '.jpg')

    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=thumbnail_key,
            Body=thumbnail_bytes,
            ContentType='image/jpeg',
            CacheControl='max-age=31536000'  # Cache for 1 year
        )
        log['upload'](f"Uploaded thumbnail: s3://{S3_BUCKET}/{thumbnail_key}")
        return thumbnail_key
    except Exception as e:
        log['error'](f"Upload failed: {e}")
        return None

def update_dynamodb_record(table, video_key, thumbnail_key):
    """Update DynamoDB record with thumbnail URL."""
    try:
        # Parse device_id and timestamp from video key
        # S3 Format: videos/device_id/2025-04-25T13-35-10-555752.mp4
        # DB Format: 2025-04-25T13:35:10.555752
        parts = video_key.split('/')
        if len(parts) >= 3:
            device_id = parts[1]
            filename_timestamp = parts[2].replace('.mp4', '')

            # Convert filename timestamp format to DynamoDB timestamp format
            # From: 2025-04-25T13-35-10-555752
            # To:   2025-04-25T13:35:10.555752
            if 'T' in filename_timestamp:
                date_part, time_part = filename_timestamp.split('T')
                # Replace hyphens with colons in time part (except the last one which should be a dot)
                time_parts = time_part.split('-')
                if len(time_parts) == 4:  # hour-minute-second-microsecond
                    db_timestamp = f"{date_part}T{time_parts[0]}:{time_parts[1]}:{time_parts[2]}.{time_parts[3]}"
                else:
                    # Fallback to original if format is unexpected
                    db_timestamp = filename_timestamp
            else:
                db_timestamp = filename_timestamp

            # Update the item with thumbnail URL
            thumbnail_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{thumbnail_key}"

            response = table.update_item(
                Key={
                    'device_id': device_id,
                    'timestamp': db_timestamp
                },
                UpdateExpression='SET thumbnail_url = :url',
                ExpressionAttributeValues={
                    ':url': thumbnail_url
                },
                ReturnValues='UPDATED_NEW'
            )
            log['success'](f"Updated DynamoDB record for {device_id}/{db_timestamp}")
            return True
        else:
            log['warning'](f"Could not parse device_id/timestamp from {video_key}")
            return False
    except Exception as e:
        log['error'](f"DynamoDB update failed: {e}")
        return False

def process_video(s3_client, dynamodb_table, video, index, total, update_db=True):
    """Process a single video: download, generate thumbnail, upload, update DB."""
    global total_thumbnails_created, failed_videos

    video_key = video['key']
    video_id = video_key.split('/')[-1].replace('.mp4', '')

    log['info'](f"[{index}/{total}] Processing {video_id}")

    # Check if thumbnail already exists
    if check_thumbnail_exists(s3_client, video_key):
        log['success'](f"Thumbnail already exists, skipping")
        return True

    # Download partial video
    log['download'](f"Downloading first 2MB of video...")
    video_bytes, downloaded = download_partial_video(s3_client, video_key)

    if not video_bytes:
        log['error'](f"Failed to download video")
        failed_videos.append(video_id)
        return False

    log['info'](f"Downloaded {downloaded / 1024:.1f} KB")

    # Generate thumbnail
    thumbnail_bytes = generate_thumbnail_from_bytes(video_bytes, video_key)

    # If first attempt fails, try downloading more data (up to 5MB)
    if not thumbnail_bytes and downloaded < 5 * 1024 * 1024:
        log['warning'](f"First attempt failed, trying with 5MB...")
        video_bytes, downloaded = download_partial_video(s3_client, video_key, max_size=5 * 1024 * 1024)
        if video_bytes:
            log['info'](f"Downloaded {downloaded / 1024:.1f} KB")
            thumbnail_bytes = generate_thumbnail_from_bytes(video_bytes, video_key)

    if not thumbnail_bytes:
        log['error'](f"Failed to generate thumbnail")
        failed_videos.append(video_id)
        return False

    # Upload to S3
    thumbnail_key = upload_thumbnail_to_s3(s3_client, thumbnail_bytes, video_key)
    if thumbnail_key:
        total_thumbnails_created += 1

        # Update DynamoDB if enabled
        if update_db:
            update_dynamodb_record(dynamodb_table, video_key, thumbnail_key)

        log['success'](f"✅ Completed {video_id}")
        return True
    else:
        failed_videos.append(video_id)
        return False

def print_summary():
    """Print final summary statistics."""
    global total_bytes_downloaded, total_thumbnails_created, failed_videos

    print("\n" + "="*60)
    log['info']("📊 THUMBNAIL GENERATION SUMMARY")
    print("="*60)

    mb_downloaded = total_bytes_downloaded / (1024 * 1024)
    gb_downloaded = mb_downloaded / 1024
    estimated_cost = gb_downloaded * COST_PER_GB

    log['success'](f"Thumbnails created: {total_thumbnails_created}")
    log['info'](f"Total data downloaded: {mb_downloaded:.2f} MB")
    log['info'](f"Estimated AWS cost: ${estimated_cost:.4f}")
    log['info'](f"Average size per video: {mb_downloaded / max(total_thumbnails_created, 1):.2f} MB")

    if failed_videos:
        log['warning'](f"Failed videos: {len(failed_videos)}")
        for video_id in failed_videos[:10]:  # Show first 10
            print(f"  - {video_id}")
        if len(failed_videos) > 10:
            print(f"  ... and {len(failed_videos) - 10} more")

    print("="*60)

def process_batch(videos, batch_size=3, dry_run=False, update_db=True):
    """Process videos in batches."""
    s3_client = get_s3_client()
    dynamodb_table = get_dynamodb_table() if update_db else None

    if dry_run:
        log['warning']("DRY RUN MODE - Processing first 3 videos only")
        videos = videos[:3]
        update_db = False  # Don't update DB in dry run mode

    total = len(videos)
    log['info'](f"Starting to process {total} videos in batches of {CONCURRENT_WORKERS}")
    if update_db:
        log['info']("DynamoDB updates ENABLED")
    else:
        log['warning']("DynamoDB updates DISABLED")

    start_time = time.time()

    # Process videos with thread pool
    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = []
        for i, video in enumerate(videos, 1):
            future = executor.submit(process_video, s3_client, dynamodb_table, video, i, total, update_db)
            futures.append(future)

            # Limit concurrent tasks
            if len(futures) >= CONCURRENT_WORKERS:
                for f in as_completed(futures[:CONCURRENT_WORKERS]):
                    f.result()
                futures = futures[CONCURRENT_WORKERS:]

        # Wait for remaining tasks
        for f in as_completed(futures):
            f.result()

    elapsed = time.time() - start_time
    log['success'](f"Completed in {elapsed:.1f} seconds")

    return total_thumbnails_created

def verify_thumbnails(count=3):
    """Verify thumbnails were created in S3."""
    log['info']("Verifying thumbnails in S3...")
    s3 = get_s3_client()

    response = s3.list_objects_v2(
        Bucket=S3_BUCKET,
        Prefix='thumbnails/',
        MaxKeys=count
    )

    if 'Contents' in response:
        log['success'](f"Found {len(response['Contents'])} thumbnails:")
        for obj in response['Contents']:
            size_kb = obj['Size'] / 1024
            print(f"  📷 {obj['Key']} ({size_kb:.1f} KB)")
        return True
    else:
        log['warning']("No thumbnails found")
        return False

def main():
    """Main execution function."""
    print("🎬 Sidara Video Thumbnail Generator")
    print("="*60)

    # Check for dry run mode
    dry_run = '--dry-run' in sys.argv or '--test' in sys.argv
    no_db = '--no-db' in sys.argv or '--no-dynamodb' in sys.argv
    update_db = not no_db and not dry_run

    if dry_run:
        log['warning']("Running in TEST MODE - will process only 3 videos")
        log['warning']("DynamoDB updates disabled in test mode")
    elif no_db:
        log['warning']("Running with DynamoDB updates DISABLED")

    try:
        # Get list of videos
        videos = list_videos_from_s3()

        if not videos:
            log['error']("No videos found in S3")
            return

        # Process videos
        process_batch(videos, dry_run=dry_run, update_db=update_db)

        # Print summary
        print_summary()

        # Verify uploads
        if dry_run:
            print("\n🔍 Verifying uploads with AWS CLI:")
            verify_thumbnails(3)

            print("\n💡 To verify with AWS CLI, run:")
            print(f"  aws s3 ls s3://{S3_BUCKET}/thumbnails/ --recursive | head -5")
            print(f"\n💡 To run with DynamoDB updates:")
            print(f"  python generate_thumbnails.py")

    except KeyboardInterrupt:
        log['warning']("Interrupted by user")
        print_summary()
    except Exception as e:
        log['error'](f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()