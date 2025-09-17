#!/usr/bin/env python3
"""
SIDARA Video Footage Analysis Script

This script analyzes video footage data for SIDARA devices by querying the
sensing-garden-videos DynamoDB table and S3 bucket to gather comprehensive
metrics for stakeholder presentation.

CRITICAL: READ ONLY OPERATIONS - NO MODIFICATIONS TO PROD DATA
"""

import os
import boto3
import json
from datetime import datetime, timezone
from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
import statistics

# Load environment variables
load_dotenv()

# SIDARA device IDs to analyze
SIDARA_DEVICES = [
    "b8f2ed92a70e5df3",
    "e73325dab87ec077",
    "d590bf3c30b2cf25"
]

class SIDARAAanalyst:
    """Analyzer for SIDARA video footage data."""

    def __init__(self):
        """Initialize AWS clients and table connections."""
        # AWS credentials
        aws_access_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        aws_region = os.environ.get("AWS_REGION", "us-east-1")

        if not aws_access_key_id or not aws_secret_access_key:
            raise ValueError("AWS credentials not found in environment variables")

        # Initialize AWS clients
        self.dynamodb = boto3.resource(
            'dynamodb',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )

        self.s3_client = boto3.client(
            's3',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )

        # DynamoDB table
        self.videos_table = self.dynamodb.Table('sensing-garden-videos')
        self.s3_bucket = "scl-sensing-garden-videos"

    def query_device_videos(self, device_id: str) -> List[Dict[str, Any]]:
        """
        Query all videos for a specific device.

        Args:
            device_id: Device identifier

        Returns:
            List of video records from DynamoDB
        """
        print(f"Querying videos for device: {device_id}")

        videos = []
        last_evaluated_key = None

        while True:
            query_params = {
                'KeyConditionExpression': 'device_id = :device_id',
                'ExpressionAttributeValues': {':device_id': device_id}
            }

            if last_evaluated_key:
                query_params['ExclusiveStartKey'] = last_evaluated_key

            response = self.videos_table.query(**query_params)
            videos.extend(response.get('Items', []))

            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break

        print(f"Found {len(videos)} videos for device {device_id}")
        return videos

    def get_s3_video_metadata(self, video_key: str) -> Optional[Dict[str, Any]]:
        """
        Get video metadata from S3.

        Args:
            video_key: S3 key for the video

        Returns:
            S3 object metadata or None if not found
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.s3_bucket,
                Key=video_key
            )
            return {
                'size_bytes': response.get('ContentLength', 0),
                'last_modified': response.get('LastModified'),
                'content_type': response.get('ContentType'),
                'metadata': response.get('Metadata', {})
            }
        except Exception as e:
            print(f"Warning: Could not get metadata for {video_key}: {e}")
            return None

    def parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp string to datetime object."""
        try:
            # Handle various timestamp formats
            if timestamp_str.endswith('Z'):
                dt = datetime.fromisoformat(timestamp_str[:-1] + '+00:00')
            elif '+' in timestamp_str or timestamp_str.endswith('00'):
                dt = datetime.fromisoformat(timestamp_str)
            else:
                dt = datetime.fromisoformat(timestamp_str)

            # Convert to UTC if timezone aware
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            else:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt
        except Exception as e:
            print(f"Warning: Could not parse timestamp {timestamp_str}: {e}")
            return datetime.now(timezone.utc)

    def estimate_video_duration(self, metadata: Dict[str, Any]) -> float:
        """
        Estimate video duration in seconds from metadata.

        Args:
            metadata: Video metadata from various sources

        Returns:
            Estimated duration in seconds (default 60 if unknown)
        """
        # Check for duration in custom metadata
        custom_meta = metadata.get('metadata', {})
        if 'duration_seconds' in custom_meta:
            try:
                return float(custom_meta['duration_seconds'])
            except (ValueError, TypeError):
                pass

        # Try to extract from video_key naming patterns if available
        # For now, use a default assumption of 60 seconds per video
        # This could be improved with actual video file analysis
        return 60.0

    def analyze_device_videos(self, device_id: str) -> Dict[str, Any]:
        """
        Comprehensive analysis of videos for a single device.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary with analysis results
        """
        videos = self.query_device_videos(device_id)

        if not videos:
            return {
                'device_id': device_id,
                'total_videos': 0,
                'total_hours': 0,
                'total_size_gb': 0,
                'date_range': None,
                'error': 'No videos found'
            }

        # Initialize tracking variables
        total_duration_seconds = 0
        total_size_bytes = 0
        timestamps = []
        resolutions = []
        content_types = []

        print(f"Analyzing {len(videos)} videos for device {device_id}...")

        for i, video in enumerate(videos):
            if i % 100 == 0:
                print(f"  Processed {i}/{len(videos)} videos...")

            # Parse timestamp
            timestamp_str = video.get('timestamp', '')
            if timestamp_str:
                timestamps.append(self.parse_timestamp(timestamp_str))

            # Get S3 metadata if video_key exists
            video_key = video.get('video_key', '')
            s3_metadata = None
            if video_key:
                s3_metadata = self.get_s3_video_metadata(video_key)

            # Calculate duration
            if s3_metadata:
                duration = self.estimate_video_duration(s3_metadata)
                total_duration_seconds += duration
                total_size_bytes += s3_metadata.get('size_bytes', 0)

                # Track content types
                content_type = s3_metadata.get('content_type')
                if content_type:
                    content_types.append(content_type)

                # Extract resolution from metadata if available
                custom_meta = s3_metadata.get('metadata', {})
                if 'resolution' in custom_meta:
                    resolutions.append(custom_meta['resolution'])
            else:
                # Use default duration estimate
                total_duration_seconds += 60.0

        # Calculate summary statistics
        total_hours = total_duration_seconds / 3600
        total_size_gb = total_size_bytes / (1024**3)

        # Date range analysis
        date_range = None
        if timestamps:
            timestamps.sort()
            date_range = {
                'start_date': timestamps[0].isoformat(),
                'end_date': timestamps[-1].isoformat(),
                'span_days': (timestamps[-1] - timestamps[0]).days
            }

        # Resolution analysis
        resolution_stats = {}
        if resolutions:
            unique_resolutions = list(set(resolutions))
            resolution_stats = {
                'unique_resolutions': unique_resolutions,
                'most_common': max(set(resolutions), key=resolutions.count) if resolutions else None
            }

        # Content type analysis
        content_type_stats = {}
        if content_types:
            unique_types = list(set(content_types))
            content_type_stats = {
                'unique_types': unique_types,
                'most_common': max(set(content_types), key=content_types.count) if content_types else None
            }

        return {
            'device_id': device_id,
            'total_videos': len(videos),
            'total_hours': round(total_hours, 2),
            'total_size_gb': round(total_size_gb, 2),
            'date_range': date_range,
            'resolution_stats': resolution_stats,
            'content_type_stats': content_type_stats,
            'avg_video_size_mb': round((total_size_bytes / len(videos)) / (1024**2), 2) if videos else 0
        }

    def analyze_all_sidara_devices(self) -> Dict[str, Any]:
        """
        Analyze all SIDARA devices and generate comprehensive report.

        Returns:
            Complete analysis report
        """
        print("Starting SIDARA video footage analysis...")
        print(f"Analyzing devices: {SIDARA_DEVICES}")

        device_analyses = {}

        # Analyze each device
        for device_id in SIDARA_DEVICES:
            try:
                device_analyses[device_id] = self.analyze_device_videos(device_id)
            except Exception as e:
                print(f"Error analyzing device {device_id}: {e}")
                device_analyses[device_id] = {
                    'device_id': device_id,
                    'error': str(e)
                }

        # Calculate combined statistics
        total_videos_all = sum(
            analysis.get('total_videos', 0)
            for analysis in device_analyses.values()
        )

        total_hours_all = sum(
            analysis.get('total_hours', 0)
            for analysis in device_analyses.values()
        )

        total_size_gb_all = sum(
            analysis.get('total_size_gb', 0)
            for analysis in device_analyses.values()
        )

        # Overall date range
        all_start_dates = []
        all_end_dates = []

        for analysis in device_analyses.values():
            date_range = analysis.get('date_range')
            if date_range:
                all_start_dates.append(datetime.fromisoformat(date_range['start_date']))
                all_end_dates.append(datetime.fromisoformat(date_range['end_date']))

        overall_date_range = None
        if all_start_dates and all_end_dates:
            overall_start = min(all_start_dates)
            overall_end = max(all_end_dates)
            overall_date_range = {
                'start_date': overall_start.isoformat(),
                'end_date': overall_end.isoformat(),
                'span_days': (overall_end - overall_start).days
            }

        # Generate final report
        report = {
            'analysis_timestamp': datetime.now(timezone.utc).isoformat(),
            'devices_analyzed': SIDARA_DEVICES,
            'device_analyses': device_analyses,
            'combined_statistics': {
                'total_videos': total_videos_all,
                'total_hours': round(total_hours_all, 2),
                'total_size_gb': round(total_size_gb_all, 2),
                'overall_date_range': overall_date_range,
                'avg_videos_per_device': round(total_videos_all / len(SIDARA_DEVICES), 1),
                'avg_hours_per_device': round(total_hours_all / len(SIDARA_DEVICES), 2)
            }
        }

        return report

    def print_summary_report(self, report: Dict[str, Any]) -> None:
        """
        Print a formatted summary report for stakeholder presentation.

        Args:
            report: Analysis report dictionary
        """
        print("\n" + "="*80)
        print("SIDARA VIDEO FOOTAGE ANALYSIS REPORT")
        print("="*80)
        print(f"Analysis Date: {report['analysis_timestamp']}")
        print(f"Devices Analyzed: {', '.join(report['devices_analyzed'])}")
        print()

        # Combined statistics
        combined = report['combined_statistics']
        print("COMBINED STATISTICS")
        print("-" * 40)
        print(f"Total Videos: {combined['total_videos']:,}")
        print(f"Total Hours of Footage: {combined['total_hours']:,.2f} hours")
        print(f"Total Storage Used: {combined['total_size_gb']:.2f} GB")

        if combined['overall_date_range']:
            date_range = combined['overall_date_range']
            print(f"Date Range: {date_range['start_date'][:10]} to {date_range['end_date'][:10]}")
            print(f"Time Span: {date_range['span_days']:,} days")

        print(f"Average Videos per Device: {combined['avg_videos_per_device']}")
        print(f"Average Hours per Device: {combined['avg_hours_per_device']:.2f}")
        print()

        # Per-device breakdown
        print("PER-DEVICE BREAKDOWN")
        print("-" * 40)

        for device_id, analysis in report['device_analyses'].items():
            if 'error' in analysis:
                print(f"\nDevice {device_id}: ERROR - {analysis['error']}")
                continue

            print(f"\nDevice {device_id}:")
            print(f"  Videos: {analysis['total_videos']:,}")
            print(f"  Hours: {analysis['total_hours']:,.2f}")
            print(f"  Storage: {analysis['total_size_gb']:.2f} GB")
            print(f"  Avg Video Size: {analysis['avg_video_size_mb']:.1f} MB")

            if analysis['date_range']:
                dr = analysis['date_range']
                print(f"  Date Range: {dr['start_date'][:10]} to {dr['end_date'][:10]} ({dr['span_days']} days)")

            if analysis['content_type_stats']:
                cts = analysis['content_type_stats']
                print(f"  Content Types: {', '.join(cts['unique_types'])}")

        print("\n" + "="*80)


def main():
    """Main analysis function."""
    try:
        # Initialize analyzer
        analyst = SIDARAAanalyst()

        # Perform analysis
        report = analyst.analyze_all_sidara_devices()

        # Print summary report
        analyst.print_summary_report(report)

        # Save detailed report to JSON
        output_file = f"sidara_video_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        print(f"\nDetailed analysis saved to: {output_file}")

    except Exception as e:
        print(f"Analysis failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()