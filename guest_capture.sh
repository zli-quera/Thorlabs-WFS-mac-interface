#!/bin/bash
mkdir -p /mnt/host/captures /mnt/host/diagnostics
python3 -u /mnt/host/capture_with_linux_sdk.py /mnt/host/captures "$@" > /mnt/host/diagnostics/capture_latest.log 2>&1
result=$?
echo "WFS_CAPTURE_STATUS_${result}"
