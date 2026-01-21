"""Tests for RLM Claude Recall"""
import json

import pytest

from rlm_claude_recall_mcp import (
    decode_path,
    extract_keywords,
    handle_memory_projects,
    handle_memory_recall,
    handle_memory_timeline,
    rlm_client,
)


class TestPathUtilities:
    def test_decode_path(self):
        assert decode_path("-Users-richard-projects-foo") == "/Users/richard/projects/foo"

    def test_decode_path_passthrough(self):
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
        assert extract_keywords("the a an is are") == []


class TestMemoryProjects:
    @pytest.mark.asyncio
    async def test_memory_projects_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "rlm_claude_recall_mcp.get_claude_projects_dir",
            lambda: tmp_path / "nonexistent",
        )
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
        rlm_client.session = None
        result = await handle_memory_recall({"query": "xyz123nonexistent"})
        data = json.loads(result[0].text)

        assert data["total_sessions_searched"] == 0


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
        test_content = (
            '{"type": "user", "message": {"content": "Help me fix the database connection error"}}\n'
            '{"type": "assistant", "message": {"content": [{"type": "text", "text": "I see the issue - your connection string is missing the port number."}]}}'
        )

        result = await rlm_connection.call_tool(
            "rlm_load_context", {"name": "test_session", "content": test_content}
        )
        assert result is not None

        await rlm_connection.call_tool(
            "rlm_chunk_context",
            {"name": "test_session", "strategy": "lines", "size": 50},
        )

        query_result = await rlm_connection.call_tool(
            "rlm_sub_query_batch",
            {
                "query": "What was the database issue?",
                "context_name": "test_session",
                "chunk_indices": [0],
                "provider": "claude-sdk",
                "model": "claude-haiku-4-5",
                "concurrency": 1,
            },
        )

        assert query_result is not None
        if hasattr(query_result, "content"):
            for content in query_result.content:
                if hasattr(content, "text"):
                    data = json.loads(content.text)
                    assert "results" in data

        await rlm_connection.call_tool("rlm_clear_context", {"name": "test_session"})

    @pytest.mark.asyncio
    async def test_memory_recall_full_flow(self, mock_claude_projects, rlm_connection):
        """Full integration test of memory_recall with real RLM."""
        import rlm_claude_recall_mcp

        rlm_claude_recall_mcp.rlm_client = rlm_connection

        result = await handle_memory_recall({"query": "authentication bug"})
        data = json.loads(result[0].text)

        assert data["total_sessions_searched"] >= 1
        assert "results" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not integration"])
