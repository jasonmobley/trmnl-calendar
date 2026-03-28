"""
Local development runner.

Loads environment variables from .env (if present), adds src/ to sys.path,
then invokes the Lambda handler exactly as AWS would — useful for iterating
without deploying.

Usage:
    cp .env.example .env   # fill in your ICS URLs and TRMNL webhook URL
    uv run python main.py
"""

import os
import sys
from pathlib import Path

# Add src/ to path so the Lambda modules are importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Minimal .env loader — no extra dependency required
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

from lambda_function import handler  # noqa: E402 — import after path setup

if __name__ == "__main__":
    result = handler({}, None)
    print(result)
