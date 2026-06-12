"""
mcp 管理模块
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from . import onlinemcp

MCP_DIR = Path(__file__).resolve().parent
LOCAL_DATA = MCP_DIR / "localmcpdata.json"
ONLINE_DATA = MCP_DIR / "onlinemcpdata.json"
SERVER_REGISTRY = MCP_DIR / "mcpservers.json"

_LOCAL_PREFIX = "local::"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_server_registry() -> dict:
    data = _load_json(SERVER_REGISTRY, {})
    if not isinstance(data, dict):
        data = {}
    online = _load_json(ONLINE_DATA, {})
    changed = False
    for url in online.keys():
        if url not in data:
            data[url] = {
                "url": url,
                "enabled": True,
                "name": "",
                "last_refresh_at": "",
                "last_error": "",
            }
            changed = True
    if changed:
        _save_json(SERVER_REGISTRY, data)
    return data


def _save_server_registry(data: dict) -> None:
    _save_json(SERVER_REGISTRY, data)


def list_local_mcps() -> list[dict]:
    data = _load_json(LOCAL_DATA, {})
    tools = data.get("tools", []) if isinstance(data, dict) else []
    registry = _load_server_registry()
    result = []
    for tool in tools:
        name = tool.get("name", "")
        key = f"{_LOCAL_PREFIX}{name}"
        meta = registry.get(key)
        enabled = bool(meta.get("enabled", True)) if isinstance(meta, dict) else True
        result.append(
            {
                "name": name,
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {}),
                "source": "local",
                "enabled": enabled,
            }
        )
    return result


def get_enabled_local_tool_names() -> set[str]:
    return {tool["name"] for tool in list_local_mcps() if tool.get("enabled", True)}


def set_local_tool_enabled(name: str, enabled: bool) -> dict:
    data = _load_json(LOCAL_DATA, {})
    tools = data.get("tools", []) if isinstance(data, dict) else []
    tool_names = {t.get("name") for t in tools if isinstance(t, dict)}
    if name not in tool_names:
        raise ValueError(f"本地工具不存在: {name}")
    registry = _load_server_registry()
    key = f"{_LOCAL_PREFIX}{name}"
    registry.setdefault(key, {"name": name, "kind": "local_tool"})
    registry[key]["enabled"] = bool(enabled)
    _save_server_registry(registry)
    tool = next((t for t in tools if t.get("name") == name), {})
    return {
        "id": key,
        "kind": "local",
        "name": name,
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema", {}),
        "source": "local",
        "enabled": bool(enabled),
    }



def list_online_servers() -> list[dict]:
    registry = _load_server_registry()
    online = _load_json(ONLINE_DATA, {})
    result = []
    for url, meta in registry.items():
        if url.startswith(_LOCAL_PREFIX):  # 跳过本地工具条目，只处理在线服务器
            continue
        info = online.get(url, {}) if isinstance(online, dict) else {}
        server_info = info.get("server_info", {}) if isinstance(info, dict) else {}
        result.append(
            {
                "url": url,
                "name": meta.get("name") or server_info.get("name") or url,
                "version": server_info.get("version", ""),
                "enabled": bool(meta.get("enabled", True)),
                "tool_count": len(info.get("tools", [])) if isinstance(info, dict) else 0,
                "last_refresh_at": meta.get("last_refresh_at") or info.get("last_updated", ""),
                "last_error": meta.get("last_error") or info.get("error", ""),
            }
        )
    return result


def list_enabled_server_urls() -> set[str]:
    return {item["url"] for item in list_online_servers() if item.get("enabled")}


def _refresh_and_sync(url: str) -> dict:
    online = _load_json(ONLINE_DATA, {})
    registry = _load_server_registry()
    info = online.get(url, {}) if isinstance(online, dict) else {}
    meta = registry.setdefault(
        url,
        {
            "url": url,
            "enabled": True,
            "name": "",
            "last_refresh_at": "",
            "last_error": "",
        },
    )
    server_info = info.get("server_info", {}) if isinstance(info, dict) else {}
    meta["name"] = meta.get("name") or server_info.get("name", "")
    meta["last_refresh_at"] = info.get("last_updated", _now()) if isinstance(info, dict) else _now()
    meta["last_error"] = info.get("error", "") if isinstance(info, dict) else ""
    _save_server_registry(registry)
    return {
        "url": url,
        "name": meta.get("name") or url,
        "version": server_info.get("version", ""),
        "enabled": bool(meta.get("enabled", True)),
        "tool_count": len(info.get("tools", [])) if isinstance(info, dict) else 0,
        "last_refresh_at": meta.get("last_refresh_at", ""),
        "last_error": meta.get("last_error", ""),
    }


def add_online_server(url: str) -> dict:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("MCP URL 不能为空")
    onlinemcp.add_server(cleaned)
    registry = _load_server_registry()
    registry.setdefault(cleaned, {
        "url": cleaned,
        "enabled": True,
        "name": "",
        "last_refresh_at": "",
        "last_error": "",
    })
    _save_server_registry(registry)
    asyncio.run(onlinemcp.refresh_all())
    return _refresh_and_sync(cleaned)


def refresh_all_online_servers() -> list[dict]:
    asyncio.run(onlinemcp.refresh_all())
    return [_refresh_and_sync(item["url"]) for item in list_online_servers()]


def set_online_server_enabled(url: str, enabled: bool) -> dict:
    registry = _load_server_registry()
    if url not in registry:
        raise ValueError(f"MCP server 不存在: {url}")
    registry[url]["enabled"] = bool(enabled)
    registry[url]["last_refresh_at"] = registry[url].get("last_refresh_at") or _now()
    _save_server_registry(registry)
    return _refresh_and_sync(url)


def list_all_mcps() -> dict:
    local_tools = list_local_mcps()
    online_servers = list_online_servers()
    online = _load_json(ONLINE_DATA, {})

    interfaces: list[dict] = []
    for tool in local_tools:
        key = f"{_LOCAL_PREFIX}{tool['name']}"
        interfaces.append(
            {
                "id": key,
                "kind": "local",
                "name": tool["name"],
                "description": tool.get("description", ""),
                "enabled": tool.get("enabled", True),
                "tool_count": 1,
                "tools": [tool],
            }
        )

    if isinstance(online, dict):
        for server in online_servers:
            url = server["url"]
            info = online.get(url, {})
            if not isinstance(info, dict):
                info = {}
            interfaces.append(
                {
                    "id": url,
                    "kind": "online",
                    "url": url,
                    "name": server.get("name") or url,
                    "description": info.get("server_info", {}).get("instructions", "") or info.get("server_info", {}).get("name", ""),
                    "version": server.get("version", ""),
                    "enabled": bool(server.get("enabled", True)),
                    "tool_count": len(info.get("tools", [])),
                    "last_refresh_at": server.get("last_refresh_at", ""),
                    "last_error": server.get("last_error", ""),
                    "tools": [
                        {
                            "name": t.get("name", ""),
                            "description": t.get("description", ""),
                            "inputSchema": t.get("inputSchema", {}),
                            "source": "online",
                        }
                        for t in info.get("tools", [])
                    ],
                }
            )
    return {
        "items": interfaces,
        "online_servers": online_servers,
    }
