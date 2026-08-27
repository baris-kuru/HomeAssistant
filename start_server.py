#!/usr/bin/env python3
"""Start the HomeAssistant server in a truly detached background process."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

def start():
    # Use start_new_session=True to detach from terminal
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "backend.main:app",
            "--host", "0.0.0.0",
            "--port", "8001",
            "--ssl-keyfile", str(ROOT / "key.pem"),
            "--ssl-certfile", str(ROOT / "cert.pem"),
        ],
        cwd=str(ROOT),
        stdout=open("/tmp/ha_server.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"Server started with PID {proc.pid}")
    print("Logs: tail -f /tmp/ha_server.log")

if __name__ == "__main__":
    start()
