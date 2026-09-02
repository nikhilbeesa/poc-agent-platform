"""WSGI entry point for production deployment (Render).
Render's start command runs: gunicorn wsgi:app"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "webapp"))
from server import app  # noqa: E402,F401
