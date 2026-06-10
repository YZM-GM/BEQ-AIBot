"""
聊天与会话管理
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONVERSATIONS_FILE = BASE_DIR / "conversations.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_store() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONVERSATIONS_FILE.exists():
        with open(CONVERSATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def _load() -> list[dict]:
    _ensure_store()
    try:
        with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [_normalize(item) for item in data if isinstance(item, dict)]


def _save(items: list[dict]) -> None:
    _ensure_store()
    with open(CONVERSATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _normalize(item: dict) -> dict:
    now = _now()
    members = item.get("member_agents") or []
    if not isinstance(members, list):
        members = []
    return {
        "id": item.get("id") or f"conv-{uuid.uuid4()}",
        "type": item.get("type") if item.get("type") in {"single", "group"} else "single",
        "title": item.get("title") or "未命名会话",
        "owner_agent": item.get("owner_agent") or "",
        "member_agents": [name for name in members if isinstance(name, str) and name.strip()],
        "created_at": item.get("created_at") or now,
        "updated_at": item.get("updated_at") or now,
        "last_message_preview": item.get("last_message_preview") or "",
    }


def list_conversations() -> list[dict]:
    return _load()


def get_conversation(conversation_id: str) -> dict | None:
    for item in _load():
        if item["id"] == conversation_id:
            return item
    return None


def create_conversation(title: str, conversation_type: str, owner_agent: str, member_agents: list[str] | None = None) -> dict:
    cleaned_type = conversation_type if conversation_type in {"single", "group"} else "single"
    members = [name.strip() for name in (member_agents or []) if isinstance(name, str) and name.strip()]
    if cleaned_type == "single":
        members = members[:1] if members else ([owner_agent] if owner_agent else [])
    elif owner_agent and owner_agent not in members:
        members = [owner_agent, *members]

    now = _now()
    item = _normalize(
        {
            "id": f"conv-{uuid.uuid4()}",
            "type": cleaned_type,
            "title": (title or "").strip() or ("群聊" if cleaned_type == "group" else owner_agent or "单聊"),
            "owner_agent": owner_agent,
            "member_agents": members,
            "created_at": now,
            "updated_at": now,
            "last_message_preview": "",
        }
    )
    items = _load()
    items.append(item)
    _save(items)
    return item


def update_conversation(conversation_id: str, **updates) -> dict:
    items = _load()
    for index, item in enumerate(items):
        if item["id"] != conversation_id:
            continue
        merged = dict(item)
        merged.update(updates)
        merged["updated_at"] = _now()
        items[index] = _normalize(merged)
        _save(items)
        return items[index]
    raise ValueError(f"conversation 不存在: {conversation_id}")


def ensure_single_conversation(agent_name: str) -> dict:
    for item in _load():
        if item["type"] == "single" and item.get("owner_agent") == agent_name:
            return item
    return create_conversation(agent_name, "single", agent_name, [agent_name])
