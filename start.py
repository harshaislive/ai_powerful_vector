#!/usr/bin/env python3
import os
import subprocess
import sys

def main():
    # Get the port from environment variable, fallback to 8000
    port = os.environ.get("PORT", "8000")
    
    # Build the uvicorn command
    cmd = [
        "uvicorn",
        "main:app",
        "--host", "0.0.0.0",
        "--port", port,
        "--log-level", "info"
    ]
    
    print(f"Starting server on port {port}")
    print(f"Command: {' '.join(cmd)}")
    
    # Execute uvicorn
    subprocess.run(cmd)

if __name__ == "__main__":
    main() 