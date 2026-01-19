# RLM Claude Recall

RLM-powered semantic search for Claude Code conversation history.

## Overview

RLM Claude Recall provides three tools for exploring your Claude Code conversation history:

- **memory_projects** - Discover all projects with session counts and sizes
- **memory_timeline** - Browse recent sessions with summaries
- **memory_recall** - Semantic search across conversations using RLM

### Architecture

```
                    Claude Code (Main)
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
  RLM Claude Recall  RLM MCP Server   Other MCPs
           │                  ▲
           │   MCP Client     │
           └──────────────────┘
                   │
                   ▼
    ~/.claude/projects/
    ├── -Users-richard-projects-foo/
    │   ├── {session}.jsonl
    │   └── {session}/session-memory/summary.md
```

RLM Claude Recall is **dual-role**: It's an MCP server (exposing tools to Claude) and an MCP client (calling RLM tools for semantic search).

## Installation

### 1. Install RLM Claude Recall

```bash
cd /path/to/rlm-claude-recall
uv pip install -e .
```

### 2. Configure Claude Code

Add to `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "rlm-claude-recall": {
      "command": "uv",
      "args": ["run", "rlm-claude-recall"],
      "cwd": "/path/to/rlm-claude-recall",
      "env": {
        "RLM_SERVER_PATH": "/path/to/rlm"
      }
    }
  }
}
```

### 3. Ensure RLM is Available

RLM Claude Recall requires the RLM MCP server for semantic search (`memory_recall`). Install RLM:

```bash
cd /path/to/rlm
uv pip install -e .
```

## Tools

### memory_projects

List all Claude Code projects with session counts and storage sizes.

**Input:** None

**Output:**
```json
{
  "projects": [
    {
      "path": "/Users/richard/projects/myapp",
      "session_count": 45,
      "last_used": "2026-01-18T10:30:00",
      "total_size_mb": 12.5
    }
  ],
  "total_projects": 15,
  "total_sessions": 452,
  "total_size_gb": 4.6
}
```

### memory_timeline

View recent sessions with summaries and metadata.

**Input:**
- `days` (optional, default: 7) - Number of days to look back
- `project` (optional) - Filter by project path substring

**Output:**
```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "project": "/Users/richard/projects/myapp",
      "summary": "Fixed authentication bug",
      "timestamp": "2026-01-18T10:30:00",
      "model": "claude-sonnet-4"
    }
  ],
  "total_sessions": 12,
  "date_range": "Last 7 days"
}
```

### memory_recall

Semantic search across conversation history using RLM.

**Input:**
- `query` (required) - Natural language question
- `project` (optional) - Filter by project path

**Algorithm:**
1. Extract keywords and grep summaries for pre-filtering
2. Load top 10 matching sessions into RLM
3. Run `rlm_sub_query_batch` with Claude Haiku for semantic search
4. Return top 5 most relevant results

**Output:**
```json
{
  "results": [
    {
      "session_id": "abc123",
      "project": "/Users/richard/projects/myapp",
      "summary": "Fixed authentication bug",
      "timestamp": "2026-01-18T10:30:00",
      "relevance": "high - directly addresses login issue",
      "excerpt": "The bug was in the JWT validation logic..."
    }
  ],
  "total_sessions_searched": 10
}
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RLM_SERVER_PATH` | `/Users/richard/projects/fun/rlm` | Path to RLM MCP server |

## Usage Examples

```
User: "Show my Claude Code projects"
Claude: memory_projects()
→ 45 projects, 452 sessions, 4.6GB total

User: "What did I work on this week?"
Claude: memory_timeline(days=7)
→ 12 sessions listed by project and title

User: "How did I fix the ADK State bug?"
Claude: memory_recall(query="ADK State bug fix")
→ Found in session 6f3a7e75: "Fixed by dual-path pattern..."
```

## Development

### Install dev dependencies

```bash
uv pip install -e ".[dev]"
```

### Run tests

```bash
# Unit tests only (no RLM required)
pytest tests/ -v -m "not integration"

# Integration tests (requires running RLM server)
pytest tests/ -v -m integration

# All tests
pytest tests/ -v
```

## Requirements

- Python 3.10+
- MCP library
- RLM MCP server (for `memory_recall`)
- Claude Code with conversation history in `~/.claude/projects/`

## License

MIT
