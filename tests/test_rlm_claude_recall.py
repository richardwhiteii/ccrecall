"""Tests for RLM Claude Recall"""
import pytest
import json
from pathlib import Path
from datetime import datetime
import os

# Import from our module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rlm_claude_recall_mcp import (
    decode_path, extract_keywords,
    handle_memory_projects, handle_memory_timeline, handle_memory_recall,
    get_claude_projects_dir, rlm_client, RLMClient
)


class TestPathUtilities:
    def test_decode_path(self):
        assert decode_path("-Users-richard-projects-foo") == "/Users/richard/projects/foo"

    def test_decode_path_passthrough(self):
        # Non-encoded paths should pass through unchanged
        assert decode_path("regular-string") == "regular-string"

    def test_decode_hyphenated_path(self):
        # Paths with hyphens in directory names get converted
        # This documents the known limitation (matches Claude's behavior)
        assert decode_path("-Users-richard-projects-my-app") == "/Users/richard/projects/my/app"


class TestKeywordExtraction:
    def test_extract_keywords(self):
        keywords = extract_keywords("How did I fix the authentication bug?")
        assert "fix" in keywords
        assert "authentication" in keywords
        assert "bug" in keywords
        assert "how" not in keywords
        assert "the" not in keywords

    def test_extract_keywords_empty(self):
        assert extract_keywords("") == []

    def test_extract_keywords_only_stop_words(self):
        keywords = extract_keywords("the a an is are")
        assert keywords == []


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
            "uuid": "user-123"
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4",
                "role": "assistant",
                "content": [{"type": "text", "text": "I'll help you fix the authentication bug. The issue is in the login handler."}]
            },
            "timestamp": datetime.now().isoformat(),
            "uuid": "asst-123"
        },
        {"type": "summary", "summary": "Fixed authentication login bug in user service"}
    ]

    session_file = project_dir / "session-abc123.jsonl"
    with open(session_file, 'w') as f:
        for entry in session_data:
            f.write(json.dumps(entry) + "\n")

    return projects_dir


@pytest.fixture
def mock_claude_projects(temp_projects_dir, monkeypatch):
    """Patch get_claude_projects_dir to use temp directory."""
    monkeypatch.setattr("rlm_claude_recall_mcp.get_claude_projects_dir", lambda: temp_projects_dir)
    return temp_projects_dir


class TestMemoryProjects:
    @pytest.mark.asyncio
    async def test_memory_projects_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rlm_claude_recall_mcp.get_claude_projects_dir", lambda: tmp_path / "nonexistent")

        result = await handle_memory_projects()
        data = json.loads(result[0].text)

        assert data["total_projects"] == 0
        assert data["total_sessions"] == 0

    @pytest.mark.asyncio
    async def test_memory_projects_with_data(self, mock_claude_projects):
        result = await handle_memory_projects()
        data = json.loads(result[0].text)

        assert data["total_projects"] == 1
        assert data["total_sessions"] == 1
        assert data["projects"][0]["path"] == "/Users/test/projects/myapp"
        assert data["projects"][0]["session_count"] == 1


class TestMemoryTimeline:
    @pytest.mark.asyncio
    async def test_memory_timeline_returns_recent(self, mock_claude_projects):
        result = await handle_memory_timeline({"days": 7})
        data = json.loads(result[0].text)

        assert data["total_sessions"] == 1
        assert "authentication" in data["sessions"][0]["summary"].lower()

    @pytest.mark.asyncio
    async def test_memory_timeline_project_filter_match(self, mock_claude_projects):
        result = await handle_memory_timeline({"days": 7, "project": "myapp"})
        data = json.loads(result[0].text)

        assert data["total_sessions"] == 1

    @pytest.mark.asyncio
    async def test_memory_timeline_project_filter_no_match(self, mock_claude_projects):
        result = await handle_memory_timeline({"days": 7, "project": "nonexistent"})
        data = json.loads(result[0].text)

        assert data["total_sessions"] == 0


class TestMemoryRecallUnit:
    """Unit tests for memory_recall that don't require RLM."""

    @pytest.mark.asyncio
    async def test_memory_recall_missing_query(self, mock_claude_projects):
        result = await handle_memory_recall({})
        data = json.loads(result[0].text)

        assert data["error"] == "MISSING_QUERY"

    @pytest.mark.asyncio
    async def test_memory_recall_no_matches(self, mock_claude_projects):
        # Query that won't match any keywords
        rlm_client.session = None  # Ensure RLM not connected
        result = await handle_memory_recall({"query": "xyz123nonexistent"})
        data = json.loads(result[0].text)

        assert data["total_sessions_searched"] == 0


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


@pytest.mark.integration
class TestMemoryRecallIntegration:
    """Integration tests that require a running RLM server."""

    @pytest.mark.asyncio
    async def test_rlm_connection(self, rlm_connection):
        """Verify we can connect to RLM."""
        assert rlm_connection.session is not None

    @pytest.mark.asyncio
    async def test_rlm_load_and_query(self, rlm_connection):
        """Test loading content into RLM and querying it."""
        # Load test content
        test_content = """{"type": "user", "message": {"content": "Help me fix the database connection error"}}
{"type": "assistant", "message": {"content": [{"type": "text", "text": "I see the issue - your connection string is missing the port number."}]}}"""

        result = await rlm_connection.call_tool("rlm_load_context", {
            "name": "test_session",
            "content": test_content
        })
        assert result is not None

        # Chunk it
        await rlm_connection.call_tool("rlm_chunk_context", {
            "name": "test_session",
            "strategy": "lines",
            "size": 50
        })

        # Query it with real LLM
        query_result = await rlm_connection.call_tool("rlm_sub_query_batch", {
            "query": "What was the database issue?",
            "context_name": "test_session",
            "chunk_indices": [0],
            "provider": "claude-sdk",
            "model": "claude-haiku-4-5",
            "concurrency": 1
        })

        assert query_result is not None
        # Parse and verify response contains relevant info
        if hasattr(query_result, 'content'):
            for content in query_result.content:
                if hasattr(content, 'text'):
                    data = json.loads(content.text)
                    assert "results" in data

        # Cleanup
        await rlm_connection.call_tool("rlm_clear_context", {"name": "test_session"})

    @pytest.mark.asyncio
    async def test_memory_recall_full_flow(self, mock_claude_projects, rlm_connection):
        """Full integration test of memory_recall with real RLM."""
        # Use the real RLM connection
        import rlm_claude_recall_mcp
        rlm_claude_recall_mcp.rlm_client = rlm_connection

        result = await handle_memory_recall({"query": "authentication bug"})
        data = json.loads(result[0].text)

        # Should find results from our test fixture
        assert data["total_sessions_searched"] >= 1
        # Results may or may not be found depending on semantic match
        assert "results" in data


if __name__ == "__main__":
    # Run unit tests by default, use -m integration for integration tests
    pytest.main([__file__, "-v", "-m", "not integration"])
