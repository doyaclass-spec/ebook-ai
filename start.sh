#!/bin/bash
apt-get update && apt-get install -y fonts-noto-cjk ghostscript && fc-cache -f
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
