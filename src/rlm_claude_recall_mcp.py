"""RLM Claude Recall - Semantic search for Claude Code conversation history"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rlm-claude-recall")

# Constants
MAX_SESSION_BYTES = 500_000  # 500KB limit per session for RLM loading
MAX_LINES_PER_SESSION = 500  # Max lines to process when truncating large sessions
MAX_SESSIONS_TO_SEARCH = 10  # Maximum sessions to load into RLM for semantic search
MAX_RESULTS = 5  # Maximum results to return from search

STOP_WORDS = frozenset({
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
    'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
    'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above',
    'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here',
    'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more',
    'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
    'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or',
    'because', 'until', 'while', 'what', 'which', 'who', 'this', 'that',
    'these', 'those', 'am', 'i', 'my', 'me', 'you', 'your', 'it'
})

def decode_path(encoded: str) -> str:
    """Convert Claude's encoded path format back to filesystem path.

    Example: -Users-richard-projects-foo -> /Users/richard/projects/foo
    """
    if not encoded.startswith("-"):
        return encoded
    return "/" + encoded[1:].replace("-", "/")


def get_claude_projects_dir() -> Path:
    """Return the Claude projects directory path."""
    return Path.home() / ".claude" / "projects"


def json_response(data: dict) -> list[TextContent]:
    """Create a JSON TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


def extract_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a query for pre-filtering."""
    words = re.findall(r'\b\w+\b', query.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]


def parse_rlm_json_response(result: Any) -> Optional[dict]:
    """Extract JSON data from an RLM tool result."""
    if not hasattr(result, 'content'):
        return None
    for content in result.content:
        if hasattr(content, 'text'):
            try:
                return json.loads(content.text)
            except json.JSONDecodeError:
                continue
    return None

class RLMClient:
    """MCP client for communicating with RLM server."""

    def __init__(self):
        self.session: Optional[ClientSession] = None
        self._read_stream = None
        self._write_stream = None
        self._client_context = None
        self._session_context = None

    async def connect(self, max_retries: int = 3) -> None:
        """Connect to RLM MCP server with retry logic."""
        rlm_path = os.environ.get("RLM_SERVER_PATH")
        if not rlm_path:
            raise RuntimeError(
                "RLM_SERVER_PATH environment variable not set. "
                "Set it to the path of your RLM installation."
            )

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "rlm-server"],
            cwd=rlm_path
        )

        for attempt in range(max_retries):
            try:
                self._client_context = stdio_client(server_params)
                self._read_stream, self._write_stream = await self._client_context.__aenter__()

                self._session_context = ClientSession(self._read_stream, self._write_stream)
                self.session = await self._session_context.__aenter__()

                await self.session.initialize()
                logger.info("Connected to RLM MCP server")
                return
            except Exception as e:
                logger.warning(f"RLM connection attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"Failed to connect to RLM after {max_retries} attempts: {e}"
                    )
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

    async def disconnect(self) -> None:
        """Disconnect from RLM MCP server."""
        if self._session_context:
            await self._session_context.__aexit__(None, None, None)
        if self._client_context:
            await self._client_context.__aexit__(None, None, None)
        self.session = None
        logger.info("Disconnected from RLM MCP server")

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call an RLM tool."""
        if not self.session:
            raise RuntimeError("Not connected to RLM server")
        return await self.session.call_tool(name, arguments)

# Global RLM client instance
rlm_client = RLMClient()

server = Server("ccrecall")

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available CCAM tools."""
    return [
        Tool(
            name="memory_projects",
            description="List all Claude Code projects with session counts and sizes",
            inputSchema={
                "type": "object",
                "properties": {},
            }
        ),
        Tool(
            name="memory_timeline",
            description="View recent Claude Code sessions with summaries",
            inputSchema={
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
        ),
        Tool(
            name="memory_recall",
            description="Semantic search across Claude Code conversation history",
            inputSchema={
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
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    handlers = {
        "memory_projects": lambda args: handle_memory_projects(),
        "memory_timeline": handle_memory_timeline,
        "memory_recall": handle_memory_recall,
    }
    handler = handlers.get(name)
    if not handler:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)


async def handle_memory_projects() -> list[TextContent]:
    """List all Claude Code projects with session counts and sizes."""
    projects_dir = get_claude_projects_dir()

    if not projects_dir.exists():
        return json_response({
            "projects": [],
            "total_projects": 0,
            "total_sessions": 0,
            "total_size_gb": 0.0
        })

    projects = []
    total_sessions = 0
    total_size_bytes = 0

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_path = decode_path(project_dir.name)
        session_files = list(project_dir.glob("*.jsonl"))
        session_count = len(session_files)
        project_size = sum(f.stat().st_size for f in project_dir.rglob("*") if f.is_file())

        last_used_iso = None
        if session_files:
            last_used = max(f.stat().st_mtime for f in session_files)
            last_used_iso = datetime.fromtimestamp(last_used).isoformat()

        projects.append({
            "path": project_path,
            "session_count": session_count,
            "last_used": last_used_iso,
            "total_size_mb": round(project_size / (1024 * 1024), 2)
        })

        total_sessions += session_count
        total_size_bytes += project_size

    projects.sort(key=lambda x: x["last_used"] or "", reverse=True)

    return json_response({
        "projects": projects,
        "total_projects": len(projects),
        "total_sessions": total_sessions,
        "total_size_gb": round(total_size_bytes / (1024 * 1024 * 1024), 2)
    })


async def handle_memory_timeline(arguments: dict) -> list[TextContent]:
    """View recent sessions within a time window."""
    days = arguments.get("days", 7)
    project_filter = arguments.get("project")

    projects_dir = get_claude_projects_dir()
    if not projects_dir.exists():
        return json_response({
            "sessions": [],
            "total_sessions": 0,
            "date_range": f"Last {days} days"
        })

    cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)
    sessions = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_path = decode_path(project_dir.name)
        if project_filter and project_filter not in project_path:
            continue

        for session_file in project_dir.glob("*.jsonl"):
            if session_file.stat().st_mtime < cutoff_time:
                continue

            session_info = await extract_session_info(session_file, project_path)
            if session_info:
                sessions.append(session_info)

    sessions.sort(key=lambda x: x["timestamp"] or "", reverse=True)

    return json_response({
        "sessions": sessions,
        "total_sessions": len(sessions),
        "date_range": f"Last {days} days"
    })


async def extract_session_info(session_file: Path, project_path: str) -> Optional[dict]:
    """Extract metadata from a session JSONL file."""
    try:
        summary = None
        timestamp = None
        model = None

        with open(session_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")
                if entry_type == "summary":
                    summary = entry.get("summary")
                elif entry_type == "user" and not timestamp:
                    timestamp = entry.get("timestamp")
                elif entry_type == "assistant" and not model:
                    model = entry.get("message", {}).get("model")

        return {
            "session_id": session_file.stem,
            "project": project_path,
            "summary": summary or "No summary available",
            "timestamp": timestamp,
            "model": model
        }
    except Exception as e:
        logger.warning(f"Error reading session {session_file}: {e}")
        return None

def read_session_content(session_file: Path) -> str:
    """Read session file content, truncating large files."""
    file_size = session_file.stat().st_size

    if file_size <= MAX_SESSION_BYTES:
        return session_file.read_text()

    logger.info(f"Session {session_file.stem} is {file_size/1024:.0f}KB, truncating")
    with open(session_file, 'r') as f:
        lines = [line for i, line in enumerate(f) if i < MAX_LINES_PER_SESSION]
    return ''.join(lines)


def build_result_entry(session_info: dict, relevance: str, excerpt: str) -> dict:
    """Build a standardized result entry."""
    return {
        "session_id": session_info["session_id"],
        "project": session_info["project"],
        "summary": session_info["summary"],
        "timestamp": session_info["timestamp"],
        "relevance": relevance,
        "excerpt": excerpt
    }


def deduplicate_results(results: list[dict], max_results: int) -> list[dict]:
    """Return unique results by session_id, up to max_results."""
    seen = set()
    unique = []
    for r in results:
        if r["session_id"] not in seen:
            seen.add(r["session_id"])
            unique.append(r)
            if len(unique) >= max_results:
                break
    return unique


async def find_matching_sessions(
    projects_dir: Path,
    keywords: list[str],
    project_filter: Optional[str]
) -> list[dict]:
    """Find sessions with keyword matches in summaries."""
    matching = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_path = decode_path(project_dir.name)
        if project_filter and project_filter not in project_path:
            continue

        for session_file in project_dir.glob("*.jsonl"):
            session_info = await extract_session_info(session_file, project_path)
            if not session_info:
                continue

            summary_lower = (session_info.get("summary") or "").lower()
            if keywords and any(kw in summary_lower for kw in keywords):
                matching.append({"file": session_file, "info": session_info})

    matching.sort(key=lambda x: x["info"].get("timestamp") or "", reverse=True)
    return matching[:MAX_SESSIONS_TO_SEARCH]


async def search_session_with_rlm(session: dict, query: str) -> list[dict]:
    """Load a session into RLM and perform semantic search."""
    session_info = session["info"]
    context_name = f"session_{session_info['session_id']}"
    results = []

    session_content = read_session_content(session["file"])

    await rlm_client.call_tool("rlm_load_context", {
        "name": context_name,
        "content": session_content
    })

    await rlm_client.call_tool("rlm_chunk_context", {
        "name": context_name,
        "strategy": "lines",
        "size": 100
    })

    inspect_result = await rlm_client.call_tool("rlm_inspect_context", {
        "name": context_name
    })

    chunk_count = 1
    data = parse_rlm_json_response(inspect_result)
    if data:
        chunk_count = data.get("chunk_count", 1)

    batch_result = await rlm_client.call_tool("rlm_sub_query_batch", {
        "query": f"Find information relevant to: {query}",
        "context_name": context_name,
        "chunk_indices": list(range(min(chunk_count, 5))),
        "provider": "claude-sdk",
        "model": "claude-haiku-4-5-20251101",
        "concurrency": 2
    })

    data = parse_rlm_json_response(batch_result)
    if data:
        for r in data.get("results", []):
            response = r.get("response", "")
            if response:
                results.append(build_result_entry(
                    session_info, "semantic_match", response[:500]
                ))

    return results


async def handle_memory_recall(arguments: dict) -> list[TextContent]:
    """Semantic search across conversation history using RLM."""
    query = arguments.get("query", "")
    project_filter = arguments.get("project")

    if not query:
        return json_response({
            "error": "MISSING_QUERY",
            "message": "Query parameter is required"
        })

    projects_dir = get_claude_projects_dir()
    if not projects_dir.exists():
        return json_response({
            "results": [],
            "total_sessions_searched": 0,
            "suggestion": "No Claude projects directory found"
        })

    keywords = extract_keywords(query)
    top_sessions = await find_matching_sessions(projects_dir, keywords, project_filter)

    if not top_sessions:
        return json_response({
            "results": [],
            "total_sessions_searched": 0,
            "suggestion": f"No sessions found matching keywords: {keywords}. Try broader terms."
        })

    # Try to connect to RLM for semantic search
    try:
        if not rlm_client.session:
            await rlm_client.connect()
    except Exception as e:
        logger.warning(f"Could not connect to RLM: {e}")
        results = [
            build_result_entry(s["info"], "keyword_match", "RLM unavailable - showing keyword matches only")
            for s in top_sessions[:MAX_RESULTS]
        ]
        return json_response({
            "results": results,
            "total_sessions_searched": len(top_sessions),
            "note": "Semantic search unavailable - showing keyword matches"
        })

    # Perform semantic search on each session
    results = []
    for session in top_sessions:
        try:
            session_results = await search_session_with_rlm(session, query)
            results.extend(session_results)
        except Exception as e:
            logger.warning(f"Error processing session {session['info']['session_id']}: {e}")
            results.append(build_result_entry(
                session["info"], "keyword_match", f"Error during semantic search: {str(e)[:100]}"
            ))

    return json_response({
        "results": deduplicate_results(results, MAX_RESULTS),
        "total_sessions_searched": len(top_sessions)
    })


async def run_server() -> None:
    """Start the CCAM MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    asyncio.run(run_server())

if __name__ == "__main__":
    main()
