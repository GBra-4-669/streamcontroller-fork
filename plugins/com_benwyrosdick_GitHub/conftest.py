import os
import sys

# Ensure the repo root is importable so tests can do
# `from backend.github_backend import ...`. The backend module is intentionally
# free of GTK/StreamController imports, so it loads standalone.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
