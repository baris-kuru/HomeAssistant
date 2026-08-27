#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "Installing dependencies..."
pip install -q -r requirements.txt

echo "Starting DNA Methylation Pipeline at http://127.0.0.1:8050"
python3 app.py
