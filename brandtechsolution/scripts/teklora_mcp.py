#!/usr/bin/env python3
"""Teklora Solutions Developer MCP Server.

Zero-dependency Model Context Protocol (MCP) server for Teklora developers and
autonomous AI coding agents (Claude Code, Cursor, Antigravity, Windsurf, Cline).

Communicates via JSON-RPC 2.0 over standard input/output (stdio).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

SERVER_NAME = "teklora-developer-mcp"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


class TekloraClient:
    """HTTP client communicating with Teklora Django APIs via API key."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()

    def _request(self, method: str, path: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Teklora-Api-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": f"TekloraMCP/{SERVER_VERSION}",
        }

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {"ok": True}
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(err_body)
            except Exception:
                parsed = {"detail": err_body}
            raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {parsed.get('detail') or parsed.get('error') or err_body}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error connecting to {self.base_url}: {exc.reason}")


# ==============================================================================
# TOOL REGISTRY & HANDLERS
# ==============================================================================

TOOLS = [
    {
        "name": "teklora_get_developer_profile",
        "description": "Fetch the authenticated developer's profile, including primary role, assigned areas, WhatsApp handle, coding languages, and account status.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "teklora_list_my_tasks",
        "description": "List engineering tasks assigned to the authenticated developer in Teklora Admin. Filter by status: 'open', 'in_review', or 'done'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "in_review", "done"],
                    "description": "Optional status filter. Defaults to open tasks.",
                },
                "search": {
                    "type": "string",
                    "description": "Optional search keyword to match in title or description.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "teklora_get_task_details",
        "description": "Get complete details of a specific Teklora task by numeric ID, including description, priority, linked repository, commit logs, and activity history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "Numeric ID of the task (e.g. 41).",
                },
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "teklora_complete_task_assignment",
        "description": "Mark the authenticated developer's assignment complete on a task. When all assignees finish, the task automatically advances on the ladder to 'In Review' for management approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "Numeric ID of the task to mark completed.",
                },
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "teklora_create_task",
        "description": "Create a new task in Teklora Tasks board. Requires appropriate task management permissions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Concise, descriptive title for the task.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed task description, acceptance criteria, and technical context.",
                },
                "priority": {
                    "type": "integer",
                    "enum": [1, 2, 3, 4],
                    "description": "Priority: 1 (Low), 2 (Normal), 3 (High), 4 (Urgent). Defaults to 2.",
                },
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "teklora_list_repositories",
        "description": "List connected GitHub repositories and tracked projects in Teklora.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "teklora_search_knowledge_base",
        "description": "Search Teklora documentation, system specifications, and memory documents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query terms.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def handle_tool_call(client: TekloraClient, name: str, arguments: Dict[str, Any]) -> str:
    """Execute tool against Teklora APIs and return human-readable text result."""
    if name == "teklora_get_developer_profile":
        data = client._request("GET", "/api/staff/me/")
        profile = data.get("profile") or {}
        lines = [
            f"# Developer Profile: @{data.get('username')}",
            f"- **Name**: {data.get('first_name', '')} {data.get('last_name', '')}".strip(),
            f"- **Work Mailbox**: {data.get('mailbox') or 'None'}",
            f"- **Personal Email**: {data.get('email')}",
            f"- **WhatsApp / Phone**: {data.get('phone') or profile.get('phone') or 'Not set'}",
            f"- **Primary Role**: {data.get('primary_role') or profile.get('primary_role') or 'Not set'}",
            f"- **GitHub**: {data.get('github_username') or profile.get('github_username') or 'Not set'}",
            f"- **Languages**: {', '.join(data.get('coding_languages') or profile.get('coding_languages', [])) or 'None'}",
            f"- **Frameworks**: {', '.join(data.get('frameworks') or profile.get('frameworks', [])) or 'None'}",
            f"- **Scopes**: {', '.join(data.get('scopes') or profile.get('scopes', [])) or 'None'}",
            f"- **Bio**: {data.get('bio') or profile.get('bio') or 'None'}",
        ]
        return "\n".join(lines)

    elif name == "teklora_list_my_tasks":
        params = {"mine": "1"}
        status = arguments.get("status")
        if status:
            params["status"] = status
        search = arguments.get("search")
        if search:
            params["q"] = search

        data = client._request("GET", "/api/work/tasks/", params=params)
        results = data.get("results", data if isinstance(data, list) else [])
        if not results:
            return "No tasks found matching criteria."

        lines = [f"# Assigned Tasks ({len(results)})"]
        for t in results:
            priority_names = {1: "Low", 2: "Normal", 3: "High", 4: "Urgent"}
            p_label = priority_names.get(t.get("priority"), str(t.get("priority")))
            assignees = ", ".join(a.get("username", "") for a in t.get("assignments", []))
            lines.append(f"- **Task #{t.get('id')}**: {t.get('title')} [{t.get('status').upper()}] (Priority: {p_label})")
            if assignees:
                lines.append(f"  Assignees: {assignees}")
            if t.get("description"):
                desc = t.get("description").strip().split("\n")[0]
                lines.append(f"  Summary: {desc[:120]}")
        return "\n".join(lines)

    elif name == "teklora_get_task_details":
        task_id = arguments["task_id"]
        t = client._request("GET", f"/api/work/tasks/{task_id}/")
        priority_names = {1: "Low", 2: "Normal", 3: "High", 4: "Urgent"}
        lines = [
            f"# Task #{t.get('id')}: {t.get('title')}",
            f"- **Status**: {t.get('status').upper()}",
            f"- **Priority**: {priority_names.get(t.get('priority'), str(t.get('priority')))}",
            f"- **Created At**: {t.get('created_at')}",
            f"- **Created By**: {t.get('created_by', {}).get('username', 'System')}",
        ]
        if t.get("repository"):
            lines.append(f"- **Repository**: {t['repository'].get('full_name')} (Branch: {t['repository'].get('default_branch', 'master')})")

        lines.append("\n## Description")
        lines.append(t.get("description") or "(No description provided)")

        assignments = t.get("assignments", [])
        if assignments:
            lines.append("\n## Assignees")
            for a in assignments:
                status = "Done" if a.get("completed_at") else "In Progress"
                lines.append(f"- @{a.get('user', {}).get('username')}: {status}")

        commits = t.get("commits", [])
        if commits:
            lines.append("\n## Linked Commits")
            for c in commits:
                lines.append(f"- `{c.get('sha', '')[:7]}`: {c.get('message', '').strip()} by @{c.get('author_username')}")

        return "\n".join(lines)

    elif name == "teklora_complete_task_assignment":
        task_id = arguments["task_id"]
        res = client._request("POST", f"/api/work/tasks/{task_id}/complete/")
        status = res.get("status", "in_review")
        return (
            f"Successfully marked assignment completed on Task #{task_id}!\n"
            f"Current task ladder status is now: {status.upper()}."
        )

    elif name == "teklora_create_task":
        payload = {
            "title": arguments["title"],
            "description": arguments.get("description", ""),
            "priority": arguments.get("priority", 2),
        }
        res = client._request("POST", "/api/work/tasks/", data=payload)
        return f"Created Task #{res.get('id')}: {res.get('title')} (Status: {res.get('status')})"

    elif name == "teklora_list_repositories":
        data = client._request("GET", "/api/work/repos/")
        results = data.get("results", data if isinstance(data, list) else [])
        if not results:
            return "No connected repositories found."
        lines = ["# Connected Repositories"]
        for r in results:
            lines.append(f"- **{r.get('full_name')}** (Default branch: {r.get('default_branch', 'master')})")
        return "\n".join(lines)

    elif name == "teklora_search_knowledge_base":
        query = arguments["query"].strip()
        # Search via public blog / projects / docs endpoint
        data = client._request("GET", "/api/posts/", params={"search": query})
        results = data.get("results", data if isinstance(data, list) else [])
        if not results:
            return f"No documentation or knowledge base records found for: '{query}'"
        lines = [f"# Search Results for '{query}'"]
        for r in results[:5]:
            lines.append(f"- **{r.get('title')}**: {r.get('excerpt') or ''}")
        return "\n".join(lines)

    raise ValueError(f"Unknown tool: {name}")


# ==============================================================================
# JSON-RPC 2.0 PROTOCOL ENGINE
# ==============================================================================

def send_json(message: Dict[str, Any]):
    """Send JSON message to stdout."""
    line = json.dumps(message)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def run_stdio_server(client: TekloraClient):
    """Serve MCP requests over stdio."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            req = json.loads(line)
        except Exception:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        # Handle requests
        if method == "initialize":
            send_json({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                    "capabilities": {
                        "tools": {},
                    },
                },
            })
        elif method == "notifications/initialized":
            pass  # Client acknowledging initialization
        elif method == "ping":
            if req_id is not None:
                send_json({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "tools/list":
            send_json({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOLS,
                },
            })
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            try:
                output = handle_tool_call(client, tool_name, tool_args)
                send_json({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": output}
                        ],
                        "isError": False,
                    },
                })
            except Exception as exc:
                send_json({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": f"Error executing {tool_name}: {str(exc)}"}
                        ],
                        "isError": True,
                    },
                })
        else:
            if req_id is not None:
                send_json({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found",
                    },
                })


def main():
    parser = argparse.ArgumentParser(description="Teklora Developer MCP Server")
    parser.add_argument("--api-key", default=os.getenv("TEKLORA_API_KEY", ""), help="Teklora developer API key")
    parser.add_argument("--base-url", default=os.getenv("TEKLORA_BASE_URL", "http://127.0.0.1:8000"), help="Teklora API base URL")
    parser.add_argument("--test", action="store_true", help="Test connection to Teklora and exit")
    args = parser.parse_args()

    api_key = args.api_key.strip()
    base_url = args.base_url.strip()

    if not api_key:
        sys.stderr.write("Error: TEKLORA_API_KEY environment variable or --api-key argument is required.\n")
        sys.exit(1)

    client = TekloraClient(base_url, api_key)

    if args.test:
        print(f"Testing connection to {base_url}...")
        try:
            profile = handle_tool_call(client, "teklora_get_developer_profile", {})
            print("Successfully authenticated!")
            print(profile)
            sys.exit(0)
        except Exception as exc:
            print(f"Test failed: {exc}")
            sys.exit(1)

    run_stdio_server(client)


if __name__ == "__main__":
    main()
