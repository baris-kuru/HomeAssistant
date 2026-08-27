#!/usr/bin/env python3
"""Register Telegram webhook with Telegram's API."""
import os
import sys
import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not BOT_TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN not set in environment")
    sys.exit(1)

# Get the webhook URL from command line or use a default
if len(sys.argv) < 2:
    print("Usage: python set_telegram_webhook.py <webhook_url>")
    print("Example: python set_telegram_webhook.py https://your-domain.com/api/telegram/webhook")
    sys.exit(1)

webhook_url = sys.argv[1]

def set_webhook():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    SECRET_TOKEN = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    payload = {
        "url": webhook_url,
        "allowed_updates": ["message"],
    }
    if SECRET_TOKEN:
        payload["secret_token"] = SECRET_TOKEN
    
    response = httpx.post(url, json=payload, timeout=30)
    data = response.json()
    
    if data.get("ok"):
        print(f"✓ Webhook registered successfully: {webhook_url}")
    else:
        print(f"✗ Failed to register webhook: {data.get('description', 'Unknown error')}")
        sys.exit(1)

def get_webhook_info():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
    response = httpx.get(url, timeout=30)
    data = response.json()
    
    if data.get("ok"):
        info = data.get("result", {})
        print(f"Current webhook URL: {info.get('url', 'Not set')}")
        print(f"Pending updates: {info.get('pending_update_count', 0)}")
    else:
        print(f"Failed to get webhook info: {data.get('description', 'Unknown error')}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--info":
        get_webhook_info()
    else:
        set_webhook()
