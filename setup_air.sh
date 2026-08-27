#!/usr/bin/env zsh
# setup_air.sh — One-shot setup for HomeAssistant on M1 Air
# Run this on the Air after copying the project folder

set -euo pipefail

PROJECT_DIR="$HOME/Projects/HomeAssistant"
CERT_DAYS=365

echo "================================"
echo "  HomeAssistant Air Setup"
echo "================================"

# 1. Find the Air's WiFi IP
AIR_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
if [[ -z "$AIR_IP" ]]; then
    echo "❌ Could not detect WiFi IP. Make sure WiFi is connected."
    exit 1
fi
echo "✅ Air IP detected: $AIR_IP"

# 2. Generate fresh SSL cert for this machine
cd "$PROJECT_DIR"
openssl req -x509 -newkey rsa:4096 \
    -keyout key.pem -out cert.pem -days "$CERT_DAYS" -nodes \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:$AIR_IP"
echo "✅ Generated fresh SSL certificate for localhost + $AIR_IP"

# 3. Create virtual environment
echo "🐍 Creating Python virtual environment..."
python3 -m venv "$PROJECT_DIR/.venv"

# 4. Install dependencies
echo "📦 Installing dependencies..."
source "$PROJECT_DIR/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"

# 5. Clean up old runtime artifacts
echo "🧹 Cleaning old cache files..."
find "$PROJECT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PROJECT_DIR" -name "*.pyc" -delete 2>/dev/null || true
rm -f "$PROJECT_DIR/persona.db-shm" "$PROJECT_DIR/persona.db-wal" 2>/dev/null || true

# 6. Start the server
echo "🚀 Starting server..."
nohup uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8001 \
    --ssl-keyfile "$PROJECT_DIR/key.pem" \
    --ssl-certfile "$PROJECT_DIR/cert.pem" \
    > /tmp/ha_server.log 2>&1 &

sleep 2
PID=$(lsof -ti:8001 2>/dev/null || echo "")
if [[ -n "$PID" ]]; then
    echo "✅ Server running on PID $PID"
    echo ""
    echo "🔗 Local:     https://localhost:8001"
    echo "🔗 iPhone:    https://$AIR_IP:8001"
    echo ""
    echo "To check health: curl -sk https://localhost:8001/api/health"
    echo "To stop:         kill $(lsof -ti:8001)"
    echo "Logs:            tail -f /tmp/ha_server.log"
else
    echo "❌ Server failed to start. Check /tmp/ha_server.log"
    exit 1
fi
