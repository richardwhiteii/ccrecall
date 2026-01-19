# RLM Claude Recall

## Overview

RLM Claude Recall is an MCP server that makes Claude Code conversation history queryable via semantic search. It connects to RLM (Recursive Language Model) as an MCP client for LLM-powered search.

## Architecture

```
Claude Code → RLM Claude Recall (MCP Server) → RLM (MCP Client) → Claude Haiku
                         ↓
                ~/.claude/projects/
```

Dual-role: MCP server (to Claude) and MCP client (to RLM).

## Tools

| Tool | Purpose |
|------|---------|
| `memory_projects()` | List all projects with session counts |
| `memory_timeline(days, project)` | View recent sessions |
| `memory_recall(query, project)` | Semantic search via RLM |

## Development

```bash
# Install
uv pip install -e ".[dev]"

# Test (unit only)
uv run pytest tests/ -v -m "not integration"

# Test (with RLM)
RLM_SERVER_PATH=/path/to/rlm uv run pytest tests/ -v -m integration
```

## Key Files

- `src/rlm_claude_recall_mcp.py` - Main MCP server
- `tests/test_rlm_claude_recall.py` - Unit + integration tests

## Configuration

Set `RLM_SERVER_PATH` environment variable to point to RLM installation.

## Notes for AI Agents

- Large session files (>500KB) are truncated to 500 lines for RLM processing
- Keyword pre-filtering reduces sessions before expensive LLM calls
- Falls back to keyword matches if RLM unavailable
