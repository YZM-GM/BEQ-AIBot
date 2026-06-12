"""
统一工具注册表

职责：
  1. 从 localmcpdata.json / onlinemcpdata.json 加载工具规范，转为 OpenAI function-calling 格式
  2. 维护工具来源映射 {tool_name -> "local" | server_url}
  3. 执行分发：本地工具直接调用 Python async 函数；在线工具通过 SSE ClientSession.call_tool()
"""

import inspect
import json
import os
from pathlib import Path
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

import core.mcp.localmcp as lm
from core.mcp.mcpmanager import list_enabled_server_urls, get_enabled_local_tool_names

_LOCAL_FUNCS: dict[str, object] = {
    "list_directory": lm.list_directory,
    "create_text_file": lm.create_text_file,
    "read_file": lm.read_file,
    "run_bash_command": lm.run_bash_command,
    "task_generate": lm.task_generate,
    "get_skill": lm.get_skill,
    "request_url": lm.request_url,
}

_MCP_DIR = Path(__file__).resolve().parent
_LOCAL_DATA = _MCP_DIR / "localmcpdata.json"
_ONLINE_DATA = _MCP_DIR / "onlinemcpdata.json"


def _load_json(path: str | Path) -> dict | list:
    path = os.path.normpath(str(path))
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _to_openai_spec(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        },
    }


def _is_tool_allowed(tool_name: str, interface_id: str, allow_set: set[str] | None) -> bool:
    if allow_set is None:
        return True
    # 허용 목록이 "local" 하나만 있으면 모든 로컬 도구 허용 (레거시 지원)
    if "local" in allow_set:
        return True
    return tool_name in allow_set or interface_id in allow_set


def get_all_tools_spec(allow_mcps: list[str] | None = None) -> list[dict]:
    specs: list[dict] = []
    allow_set = set(allow_mcps) if allow_mcps else None
    globally_enabled_local = get_enabled_local_tool_names()

    local = _load_json(_LOCAL_DATA)
    for tool in local.get("tools", []):
        tool_name = tool.get("name", "")
        if tool_name not in globally_enabled_local:
            continue
        if not _is_tool_allowed(tool_name, f"local::{tool_name}", allow_set):
            continue
        specs.append(_to_openai_spec(tool))

    enabled_servers = list_enabled_server_urls()
    online = _load_json(_ONLINE_DATA)
    for url, info in online.items():
        if url not in enabled_servers or not isinstance(info, dict) or "tools" not in info:
            continue
        for tool in info["tools"]:
            if not _is_tool_allowed(tool.get("name", ""), url, allow_set):
                continue
            specs.append(_to_openai_spec(tool))

    return specs


def _build_source_map(allow_mcps: list[str] | None = None) -> dict[str, str]:
    source: dict[str, str] = {}
    allow_set = set(allow_mcps) if allow_mcps else None
    globally_enabled_local = get_enabled_local_tool_names()

    local = _load_json(_LOCAL_DATA)
    for tool in local.get("tools", []):
        tool_name = tool.get("name", "")
        if tool_name not in globally_enabled_local:
            continue
        if not _is_tool_allowed(tool_name, f"local::{tool_name}", allow_set):
            continue
        source[tool_name] = "local"

    enabled_servers = list_enabled_server_urls()
    online = _load_json(_ONLINE_DATA)
    for url, info in online.items():
        if url not in enabled_servers or not isinstance(info, dict) or "tools" not in info:
            continue
        for tool in info["tools"]:
            if not _is_tool_allowed(tool.get("name", ""), url, allow_set):
                continue
            source[tool["name"]] = url

    return source


async def execute_tool(agent: Any, name: str, arguments: dict) -> str:
    allow_mcps = None
    if getattr(agent, "config", None):
        allow_mcps = agent.config.get("allowed_mcps") or None
    source_map = _build_source_map(allow_mcps=allow_mcps)
    source = source_map.get(name)

    if source is None:
        return f"[错误] 未找到工具: {name}"

    if source == "local":
        func = _LOCAL_FUNCS.get(name)
        if func is None:
            return f"[错误] 本地工具未注册: {name}"
        call_arguments = dict(arguments)
        params = inspect.signature(func).parameters
        if "agent" in params:
            call_arguments["agent"] = agent
        try:
            result = await func(**call_arguments)
        except Exception as exc:
            return f"[工具调用失败] {name}: {exc}"
        return str(result)

    try:
        async with sse_client(source) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                call_result = await session.call_tool(name, arguments)
        parts = []
        for block in (call_result.content if call_result else []):
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else "[工具返回空结果]"
    except Exception as exc:
        return f"[工具调用失败] {name}: {exc}"
