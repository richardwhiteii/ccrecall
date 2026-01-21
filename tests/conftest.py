"""Pytest configuration and fixtures for rlm-claude-recall tests."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rlm_claude_recall_mcp import RLMClient


@pytest.fixture
def temp_projects_dir(tmp_path):
    """Create a temporary Claude projects directory with sample data."""
    projects_dir = tmp_path / ".claude" / "projects"
    projects_dir.mkdir(parents=True)

    # Create a sample project
    project_name = "-Users-test-projects-myapp"
    project_dir = projects_dir / project_name
    project_dir.mkdir()

    # Create sample session JSONL with realistic data
    session_data = [
        {
            "type": "user",
            "message": {"role": "user", "content": "Fix the authentication login bug"},
            "timestamp": datetime.now().isoformat(),
            "uuid": "user-123",
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "I'll help you fix the authentication bug. The issue is in the login handler.",
                    }
                ],
            },
            "timestamp": datetime.now().isoformat(),
            "uuid": "asst-123",
        },
        {"type": "summary", "summary": "Fixed authentication login bug in user service"},
    ]

    session_file = project_dir / "session-abc123.jsonl"
    with open(session_file, "w") as f:
        for entry in session_data:
            f.write(json.dumps(entry) + "\n")

    return projects_dir


@pytest.fixture
def mock_claude_projects(temp_projects_dir, monkeypatch):
    """Patch get_claude_projects_dir to use temp directory."""
    monkeypatch.setattr(
        "rlm_claude_recall_mcp.get_claude_projects_dir", lambda: temp_projects_dir
    )
    return temp_projects_dir


@pytest.fixture
async def rlm_connection():
    """Fixture that provides a real RLM connection. Skips if unavailable."""
    client = RLMClient()
    try:
        await client.connect(max_retries=1)
        yield client
        await client.disconnect()
    except Exception as e:
        pytest.skip(f"RLM server not available: {e}")
