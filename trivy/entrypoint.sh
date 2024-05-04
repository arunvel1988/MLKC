#!/bin/bash
set -e

# Run Trivy with arguments passed to the script, using the cache directory
trivy image --cache-dir /root/.cache/trivy --severity HIGH,CRITICAL --format json --no-progress "$@"
