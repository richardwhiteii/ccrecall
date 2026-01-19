# Implementation Plan: Claude Code Agent Memory MCP Server

## Executive Summary

A **separate MCP server** called "Claude Code Agent Memory" (CCAM) that makes Claude Code conversation history queryable using RLM via MCP protocol. Three core tools for semantic recall, timeline analysis, and project discovery.

---

## 1. Architecture

```
                    Claude Code (Main)
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    CCAM MCP Server   RLM MCP Server   Other MCPs
           │                  ▲
           │   MCP Client     │
           └──────────────────┘
                   │
                   ▼
    ~/.claude/projects/
    ├── -Users-richard-projects-foo/
    │   ├── {session}.jsonl
    │   ├── {session}/session-memory/summary.md
    │   └── subagents/agent-{id}.jsonl
```

CCAM is **dual-role**: MCP server (exposing tools to Claude) and MCP client (calling RLM tools).

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Separate MCP server | RLM is primitives; CCAM is domain-specific. Avoids scope creep. |
| Uses RLM via MCP protocol | Loose coupling, independent deployability, composable services |
| MCP client-server (not direct import) | Clean separation; RLM can evolve independently; standard protocol |

---

## 2. File Structure

```
ccam/
├── pyproject.toml           # Depends on mcp library
├── src/
│   └── ccam_mcp_server.py   # MCP server + RLM client (~500 lines)
├── tests/
│   ├── test_ccam.py
│   └── fixtures/
├── README.md
└── CLAUDE.md.example
```

Note: CCAM depends on `mcp` library (not rlm-mcp-server as a Python dep). It spawns RLM as a subprocess via MCP protocol.

---

## 3. Three Core Tools

### Tool Schemas

#### `memory_recall`

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Natural language question about past conversations"
    },
    "project": {
      "type": "string",
      "description": "Optional: Limit search to specific project path"
    }
  },
  "required": ["query"]
}
```

**Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "results": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "session_id": {"type": "string"},
          "project": {"type": "string"},
          "summary": {"type": "string"},
          "timestamp": {"type": "string", "format": "date-time"},
          "relevance": {"type": "string"},
          "excerpt": {"type": "string"}
        }
      },
      "maxItems": 5
    },
    "total_sessions_searched": {"type": "integer"}
  }
}
```

#### `memory_timeline`

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "days": {
      "type": "integer",
      "description": "Number of days to look back (default: 7)",
      "default": 7
    },
    "project": {
      "type": "string",
      "description": "Optional: Limit to specific project path"
    }
  }
}
```

**Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "sessions": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "session_id": {"type": "string"},
          "project": {"type": "string"},
          "summary": {"type": "string"},
          "timestamp": {"type": "string", "format": "date-time"},
          "model": {"type": "string"}
        }
      }
    },
    "total_sessions": {"type": "integer"},
    "date_range": {"type": "string"}
  }
}
```

#### `memory_projects`

**Input Schema:**
```json
{
  "type": "object",
  "properties": {}
}
```

**Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "projects": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "session_count": {"type": "integer"},
          "last_used": {"type": "string", "format": "date-time"},
          "total_size_mb": {"type": "number"}
        }
      }
    },
    "total_projects": {"type": "integer"},
    "total_sessions": {"type": "integer"},
    "total_size_gb": {"type": "number"}
  }
}
```

---

## 4. Data Parsing

### JSONL Entry Types

| Type | Key Fields | Purpose |
|------|------------|---------|
| `queue-operation` | `operation`, `content`, `timestamp` | Internal queue management (enqueue/dequeue) |
| `user` | `message.content` (string), `uuid`, `timestamp`, `cwd`, `gitBranch` | User prompts |
| `assistant` | `message.content` (array of blocks), `message.model`, `uuid`, `parentUuid` | Claude responses |
| `progress` | `data.type`, `data.hookEvent`, `toolUseID` | Hook/tool events |
| `summary` | `summary`, `leafUuid` | Session title/summary |

### Sample Entry Structures

**user entry:**
```json
{
  "type": "user",
  "message": { "role": "user", "content": "Say only the word 'test'" },
  "uuid": "9e525552-11f3-492a-986e-67de842d372b",
  "parentUuid": null,
  "timestamp": "2025-11-28T22:36:13.282Z",
  "cwd": "/home/richard/projects/neuron_v4/hex_neuron",
  "gitBranch": "main",
  "sessionId": "cc464ddf-d9d0-48e2-b36d-0f4095af72dd",
  "version": "2.0.53"
}
```

**assistant entry:**
```json
{
  "type": "assistant",
  "message": {
    "model": "claude-sonnet-4-5-20250929",
    "role": "assistant",
    "content": [{ "type": "text", "text": "test" }],
    "usage": { "input_tokens": 3, "output_tokens": 4 }
  },
  "uuid": "1523636f-748a-46ae-9846-2ccf6e0e4654",
  "parentUuid": "9e525552-11f3-492a-986e-67de842d372b",
  "timestamp": "2025-11-28T22:36:15.239Z",
  "requestId": "req_011CVb5yQ8Nc3Td6M3PRqQ7E"
}
```

**summary entry:**
```json
{
  "type": "summary",
  "summary": "Simple Echo Response Task",
  "leafUuid": "1523636f-748a-46ae-9846-2ccf6e0e4654"
}
```

**progress entry:**
```json
{
  "type": "progress",
  "data": {
    "type": "hook_progress",
    "hookEvent": "SessionStart",
    "hookName": "SessionStart:startup"
  },
  "toolUseID": "d836000e-c754-446d-bf76-9e86cf5f192a",
  "timestamp": "2026-01-17T02:06:38.982Z"
}
```

### Extracting Key Data

| Need | Extract From |
|------|--------------|
| Session title | `summary.summary` |
| Timestamp | `user.timestamp` or `assistant.timestamp` (ISO 8601) |
| User message | `user.message.content` (string) |
| Assistant text | `assistant.message.content[].text` where `type == "text"` |
| Project path | Decode directory name (see below) |
| Model used | `assistant.message.model` |

### Path Encoding

Claude encodes `/Users/richard/projects/foo` as `-Users-richard-projects-foo`

```python
def decode_path(encoded: str) -> str:
    """Convert -Users-richard-projects-foo to /Users/richard/projects/foo"""
    return "/" + encoded[1:].replace("-", "/")

def encode_path(path: str) -> str:
    """Convert /Users/richard/projects/foo to -Users-richard-projects-foo"""
    return "-" + path[1:].replace("/", "-")
```

---

## 5. RLM Integration (MCP Client)

### Lifecycle Management

**RLM Server Lifecycle:**
- **Spawn Once**: RLM subprocess spawned when CCAM starts
- **Keep Alive**: Maintain single RLM connection for entire CCAM session duration
- **Reconnect on Failure**: If RLM crashes/disconnects, attempt reconnection (see error handling)
- **Shutdown**: Close cleanly when CCAM receives shutdown signal

```python
class CCAMServer:
    def __init__(self):
        self.rlm_session = None
        self.rlm_connection_task = None

    async def startup(self):
        """Called once when CCAM MCP server starts"""
        self.rlm_session = await self._connect_to_rlm()

    async def shutdown(self):
        """Called when CCAM MCP server stops"""
        if self.rlm_session:
            await self.rlm_session.close()
```

### Connection Pattern

CCAM spawns RLM as a subprocess and communicates via MCP stdio transport:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def connect_to_rlm():
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "rlm-mcp-server"],
        cwd="/Users/richard/projects/fun/rlm"
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return session

# Call RLM tools via MCP protocol
result = await session.call_tool("rlm_load_context", {
    "name": "session_data",
    "content": jsonl_content
})
```

### Provider and Model Configuration

**Default Configuration for All RLM Sub-Queries:**
- **Provider**: `claude-sdk` (uses Claude API via SDK)
- **Model**: `claude-haiku-4-5` (cost-effective for recall tasks)
- **Pricing**: $1 input / $5 output per million tokens
- **Reasoning**: Memory recall is high-volume, low-complexity. Haiku 4.5 matches Sonnet 4 on coding tasks at 1/3 the cost.

```python
# When calling rlm_sub_query or rlm_sub_query_batch
result = await rlm_session.call_tool("rlm_sub_query_batch", {
    "query": "Find mentions of bug fixes",
    "context_name": "session_data",
    "chunk_indices": [0, 1, 2, 3, 4],
    "provider": "claude-sdk",
    "model": "claude-haiku-4-5",
    "concurrency": 4
})
```

### RLM Tools Used by CCAM

| RLM Tool | CCAM Use Case | Provider/Model |
|----------|---------------|----------------|
| `rlm_load_context` | Load session JSONL files into RLM | N/A (no LLM call) |
| `rlm_chunk_context` | Split large sessions into processable chunks | N/A (no LLM call) |
| `rlm_sub_query_batch` | Parallel semantic search across chunks | `claude-sdk` / `claude-haiku-4-5` |
| `rlm_auto_analyze` | One-shot summarization of sessions | `claude-sdk` / `claude-haiku-4-5` |
| `rlm_exec` | Extract user/assistant messages via Python | N/A (no LLM call) |
| `rlm_list_contexts` | Track loaded contexts | N/A (no LLM call) |

---

## 6. Memory Recall Algorithm

### Full `memory_recall(query, project?)` Flow

```python
async def memory_recall(query: str, project: str = None) -> dict:
    """
    Semantic search across conversation history using RLM.

    Algorithm:
    1. Grep summary.md files for keyword matches
    2. Load matching session JSONLs (max 10 most recent)
    3. Extract user/assistant messages via rlm_exec
    4. Run parallel semantic search with rlm_sub_query_batch
    5. Aggregate top 5 most relevant findings
    """

    # Step 1: Grep summary files for keyword matches
    summary_files = await find_summary_files(project_filter=project)
    keyword_matches = []

    for summary_file in summary_files:
        content = await read_file(summary_file)
        if any(keyword in content.lower() for keyword in extract_keywords(query)):
            keyword_matches.append({
                "session_id": extract_session_id(summary_file),
                "summary": content,
                "timestamp": extract_timestamp(summary_file)
            })

    # Sort by timestamp (most recent first), take top 10
    keyword_matches.sort(key=lambda x: x["timestamp"], reverse=True)
    top_sessions = keyword_matches[:10]

    # Step 2: Load matching session JSONLs into RLM
    for session in top_sessions:
        jsonl_path = f"~/.claude/projects/{project_dir}/{session['session_id']}.jsonl"
        jsonl_content = await read_file(jsonl_path)

        await rlm_session.call_tool("rlm_load_context", {
            "name": f"session_{session['session_id']}",
            "content": jsonl_content
        })

    # Step 3: Extract user/assistant messages via rlm_exec
    # Use Python to parse JSONL and extract only relevant messages
    extraction_code = """
import json

result = []
for line in content.split('\\n'):
    if not line.strip():
        continue
    entry = json.loads(line)

    if entry.get('type') == 'user':
        result.append({
            'role': 'user',
            'content': entry['message']['content'],
            'timestamp': entry['timestamp']
        })
    elif entry.get('type') == 'assistant':
        text_blocks = [
            block['text']
            for block in entry['message']['content']
            if block.get('type') == 'text'
        ]
        result.append({
            'role': 'assistant',
            'content': ' '.join(text_blocks),
            'timestamp': entry['timestamp']
        })
"""

    for session in top_sessions:
        await rlm_session.call_tool("rlm_exec", {
            "context_name": f"session_{session['session_id']}",
            "code": extraction_code,
            "timeout": 30
        })

        # Chunk the extracted messages
        await rlm_session.call_tool("rlm_chunk_context", {
            "name": f"session_{session['session_id']}",
            "strategy": "lines",
            "size": 100  # ~100 message pairs per chunk
        })

    # Step 4: Run parallel semantic search with rlm_sub_query_batch
    all_chunk_results = []

    for session in top_sessions:
        # Get chunk count
        inspect_result = await rlm_session.call_tool("rlm_inspect_context", {
            "name": f"session_{session['session_id']}"
        })
        chunk_count = inspect_result["chunk_count"]

        # Query all chunks in parallel
        batch_result = await rlm_session.call_tool("rlm_sub_query_batch", {
            "query": f"Find information relevant to: {query}",
            "context_name": f"session_{session['session_id']}",
            "chunk_indices": list(range(chunk_count)),
            "provider": "claude-sdk",
            "model": "claude-haiku-4-5",
            "concurrency": 4,
            "max_depth": 0  # No recursion needed for flat search
        })

        all_chunk_results.extend(batch_result["results"])

    # Step 5: Aggregate top 5 most relevant findings
    # Score results by relevance (Haiku returns this in response)
    scored_results = []
    for result in all_chunk_results:
        if result["relevance_score"] > 0.5:  # Filter low relevance
            scored_results.append({
                "session_id": result["session_id"],
                "project": decode_path(result["project_dir"]),
                "summary": result["session_summary"],
                "timestamp": result["timestamp"],
                "relevance": result["relevance_explanation"],
                "excerpt": result["relevant_excerpt"]
            })

    # Sort by relevance, take top 5
    scored_results.sort(key=lambda x: x["relevance_score"], reverse=True)
    top_results = scored_results[:5]

    return {
        "results": top_results,
        "total_sessions_searched": len(top_sessions)
    }
```

### Key Implementation Notes

1. **Keyword Matching First**: Grep summaries to narrow search space before expensive LLM calls
2. **Max 10 Sessions**: Prevents runaway costs on broad queries
3. **rlm_exec for Parsing**: More reliable than regex for JSONL extraction
4. **Batch Processing**: `rlm_sub_query_batch` with `concurrency=4` for parallel chunk analysis
5. **Relevance Filtering**: Only return results with confidence >0.5
6. **Session References**: Every result includes session_id for user to explore further

## 7. Error Handling

### Connection Failures

**RLM Connection Failed:**
```python
async def _connect_to_rlm_with_retry(max_retries=3):
    for attempt in range(max_retries):
        try:
            return await connect_to_rlm()
        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"Failed to connect to RLM after {max_retries} attempts: {e}"
                )
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

**Action**: Retry 3 times with exponential backoff. If all fail, return error to user:
```json
{
  "error": "RLM_CONNECTION_FAILED",
  "message": "Could not connect to RLM MCP server",
  "resolution": "Ensure RLM is installed: uv pip install -e /Users/richard/projects/fun/rlm"
}
```

### Data Corruption

**Corrupted JSONL File:**
```python
async def load_session_safe(session_id: str):
    try:
        jsonl_content = await read_file(f"~/.claude/projects/{session_id}.jsonl")
        await rlm_session.call_tool("rlm_load_context", {
            "name": f"session_{session_id}",
            "content": jsonl_content
        })
    except json.JSONDecodeError as e:
        logger.warning(f"Corrupted JSONL for session {session_id}: {e}")
        # Skip this file, continue with others
        return None
```

**Action**: Log warning, skip corrupted file, continue processing remaining sessions. Do not fail entire query.

### Empty Results

**No Matches Found:**
```python
if len(top_results) == 0:
    return {
        "results": [],
        "total_sessions_searched": len(top_sessions),
        "suggestion": f"No results found for '{query}'. Try broader keywords or check project filter."
    }
```

**Action**: Return helpful message suggesting:
1. Broader query terms
2. Removing project filter
3. Checking if sessions exist for that timeframe

### Tool Call Failures

**RLM Tool Error:**
```python
try:
    result = await rlm_session.call_tool("rlm_sub_query_batch", params)
except Exception as e:
    logger.error(f"RLM tool call failed: {e}")
    # Attempt graceful degradation
    return {
        "error": "RLM_TOOL_FAILED",
        "message": f"RLM operation failed: {e}",
        "partial_results": already_processed_results
    }
```

**Action**: Return partial results if available, with error indicator.

## 8. Installation

Add CCAM to `~/.claude/.mcp.json` (RLM is spawned by CCAM, not directly by Claude):

```json
{
  "mcpServers": {
    "ccam": {
      "command": "uv",
      "args": ["run", "ccam-mcp-server"],
      "cwd": "/Users/richard/projects/ccam",
      "env": {
        "RLM_SERVER_PATH": "/Users/richard/projects/fun/rlm"
      }
    }
  }
}
```

CCAM internally spawns RLM when needed. This keeps Claude's MCP config simple while allowing CCAM full control over RLM lifecycle.

---

## 9. Example Usage

### Recall
```
User: "How did I fix the ADK State bug?"
Claude: memory_recall(query="ADK State bug fix")
→ Found in session 6f3a7e75: "Fixed by dual-path pattern..."
```

### Timeline
```
User: "What did I work on this week?"
Claude: memory_timeline(days=7)
→ 12 sessions listed by project and title
```

### Projects
```
User: "Show my Claude Code projects"
Claude: memory_projects()
→ 45 projects, 452 sessions, 4.6GB total
```

---

## 10. Future Enhancements

- Embeddings for semantic search
- Cross-project pattern analysis
- On-demand summarization
- Privacy controls

---

## 11. Implementation Checklist

- [ ] Create ccam/ project structure with pyproject.toml
- [ ] Implement MCP client connection to RLM (spawn + initialize)
- [ ] Implement path encoding/decoding utilities
- [ ] Implement memory_projects() (simplest, no RLM needed)
- [ ] Implement memory_timeline() (light RLM usage)
- [ ] Implement memory_recall() with full RLM integration (sub_query_batch)
- [ ] Write tests (mock RLM responses)
- [ ] Create README

---

## Critical Reference Files

- `/Users/richard/projects/fun/rlm/src/rlm_mcp_server.py` - RLM handlers
- `/Users/richard/.claude/projects/` - Conversation history
