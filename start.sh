#!/bin/bash
set -euo pipefail

PORT="${PORT:-8080}"

exec gunicorn app:app --bind "0.0.0.0:${PORT}" --workers 2 --timeout 120
