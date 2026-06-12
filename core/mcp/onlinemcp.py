"""
第三方服务器MCP工具合集
抓取完成的工具信息存储在同目录下的onlinemcpdata.json

存储格式：{ url: 握手信息字典 }
握手信息字典结构：
  {
    "server_info": {"name": str, "version": str},
    "tools": [{"name": str, "description": str, "inputSchema": dict}, ...],
    "last_updated": ISO-8601 字符串,
    "error": str   # 仅握手失败时存在
  }
空字典 {} 表示该 URL 尚未握手。
"""

import asyncio
import json
import os
from datetime import datetime, timezone

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

_DATA_FILE = os.path.join(os.path.dirname(__file__), "onlinemcpdata.json")


def _load() -> dict:
    if not os.path.exists(_DATA_FILE):
        return {}
    with open(_DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def _handshake(url: str) -> dict:
    """对单个 SSE MCP 服务器握手，返回握手信息字典。"""
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            tools_result = await session.list_tools()

    server_info = {}
    if init_result and init_result.serverInfo:
        server_info = {
            "name": init_result.serverInfo.name,
            "version": init_result.serverInfo.version,
        }

    tools = []
    for tool in (tools_result.tools if tools_result else []):
        entry = {
            "name": tool.name,
            "description": tool.description or "",
        }
        if tool.inputSchema:
            entry["inputSchema"] = (
                tool.inputSchema
                if isinstance(tool.inputSchema, dict)
                else tool.inputSchema.model_dump()
            )
        tools.append(entry)

    return {
        "server_info": server_info,
        "tools": tools,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


async def refresh_all() -> None:
    """并行握手所有 URL，全部完成后一次写入文件。"""
    data = _load()
    if not data:
        return

    urls = list(data.keys())

    async def _refresh_one(url: str) -> tuple[str, dict]:
        try:
            print(f"[onlinemcp] 正在握手 {url}")
            info = await _handshake(url)
            print(f"[onlinemcp] 已握手 {url}")
            return url, info
        except Exception as exc:
            return url, {
                "error": str(exc),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

    results = await asyncio.gather(*[_refresh_one(url) for url in urls])
    for url, info in results:
        data[url] = info

    _save(data)


def load_tools() -> dict:
    """同步读取已握手的工具字典，格式 {url: info_dict}（跳过空值和错误条目）。"""
    data = _load()
    return {
        url: info
        for url, info in data.items()
        if info and "tools" in info
    }


def add_server(url: str) -> None:
    """向 onlinemcpdata.json 添加一个新的服务器 URL（标记为待握手）。"""
    data = _load()
    if url not in data:
        data[url] = {}
        _save(data)
        print(f"[onlinemcp] 已添加服务器 {url}，待握手。")
    else:
        print(f"[onlinemcp] 服务器 {url} 已存在。")
