# ccrecall

RLM-powered semantic search for Claude Code conversation history.

## Overview

ccrecall provides three tools for exploring your Claude Code conversation history:

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
       ccrecall      RLM MCP Server   Other MCPs
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

ccrecall is **dual-role**: It's an MCP server (exposing tools to Claude) and an MCP client (calling RLM tools for semantic search).

## Installation

### 1. Install RLM (Dependency)

ccrecall requires [RLM](https://github.com/richardwhiteii/rlm) for semantic search.

```bash
git clone https://github.com/richardwhiteii/rlm.git
cd rlm
uv pip install -e .
```

### 2. Install ccrecall

```bash
git clone https://github.com/richardwhiteii/ccrecall.git
cd ccrecall
uv pip install -e .
```

### 3. Configure Claude Code

Add both MCP servers to `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "rlm": {
      "command": "uv",
      "args": ["run", "rlm-server"],
      "cwd": "/path/to/rlm"
    },
    "ccrecall": {
      "command": "uv",
      "args": ["run", "ccrecall"],
      "cwd": "/path/to/ccrecall",
      "env": {
        "RLM_SERVER_PATH": "/path/to/rlm"
      }
    }
  }
}
```

Restart Claude Code to load the new MCP servers.

### Need Help Installing?

Claude Code can help you install and configure ccrecall. Just ask:

```
Help me install ccrecall (https://github.com/richardwhiteii/ccrecall) and
rlm (https://github.com/richardwhiteii/rlm) so I can search my Claude Code
conversation history. Clone both repos, install them with uv, and use
`claude mcp add` to configure both MCP servers.
```

Claude will walk you through each step, adapting paths to your system.

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

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `RLM_SERVER_PATH` | Yes | Path to RLM MCP server installation |

## Usage

Once both MCP servers are configured and Claude Code is restarted, you can ask Claude natural questions about your conversation history:

**Exploring your projects:**
```
You: What Claude Code projects do I have?
Claude: [uses memory_projects tool] You have 45 projects with 452 total sessions...
```

**Browsing recent work:**
```
You: What did I work on this week?
Claude: [uses memory_timeline tool] Here are your recent sessions...
```

**Semantic search across conversations:**
```
You: How did I fix the authentication bug?
Claude: [uses memory_recall tool] Found in session abc123: "The bug was in the JWT validation..."
```

Claude automatically selects the appropriate tool based on your question. The `memory_recall` tool uses RLM for semantic search, which is why both MCP servers need to be configured.

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

## License

MIT
