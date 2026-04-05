#!/bin/bash
set -euo pipefail
VERSION=$(git rev-parse --short HEAD)
BUCKET=scl-sensing-garden-web-deploy
APP_NAME=sensing-garden-web
ENV_NAME=sensing-garden-web-prod

cd "$(dirname "$0")/.."
zip -r "/tmp/app-${VERSION}.zip" app.py Procfile requirements.txt templates/ static/ start.sh
aws s3 cp "/tmp/app-${VERSION}.zip" "s3://${BUCKET}/app-${VERSION}.zip"
aws elasticbeanstalk create-application-version \
  --application-name "$APP_NAME" \
  --version-label "$VERSION" \
  --source-bundle S3Bucket="$BUCKET",S3Key="app-${VERSION}.zip"
aws elasticbeanstalk update-environment \
  --environment-name "$ENV_NAME" \
  --version-label "$VERSION"
rm -f "/tmp/app-${VERSION}.zip"
echo "Deploying version ${VERSION}..."
echo "Monitor at: https://console.aws.amazon.com/elasticbeanstalk"
