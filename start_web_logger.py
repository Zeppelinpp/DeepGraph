#!/usr/bin/env python3
"""
Start DeepGraph Web Logger server
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def main():
    try:
        from src.workflow.server import start_server

        print("🚀 Start DeepGraph Web Logger system...")
        print("📊 Features:")
        print("   • Real-time log monitoring")
        print("   • Beautiful Web interface")
        print("   • Task execution tracking")
        print("   • Tool call details")
        print("   • Framework extraction")
        print("   • WebSocket real-time push")
        print()

        # Start server
        start_server(host="localhost", port=9000, reload=True)

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Please ensure the required dependencies are installed:")
        print("pip install fastapi uvicorn websockets jinja2")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Start failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
