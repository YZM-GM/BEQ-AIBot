"""
agent 管理模块
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
import asyncio
from core.soul.soul import Soul

BASE_PATH = Path(__file__).resolve().parent.parent.parent
AGENT_ROOT = BASE_PATH / "core" / "agent"
REGISTRY_FILE = AGENT_ROOT / "agents.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_agent_dirs(name: str) -> Path:
    agent_dir = AGENT_ROOT / name
    (agent_dir / "memory" / "sessions").mkdir(parents=True, exist_ok=True)
    (agent_dir / "soul").mkdir(parents=True, exist_ok=True)
    (agent_dir / "task").mkdir(parents=True, exist_ok=True)
    return agent_dir


def _normalize_entry(entry: dict) -> dict:
    now = _now()
    result = {
        "name": entry.get("name", ""),
        "soul": entry.get("soul", "default"),
        "allowed_mcps": list(entry.get("allowed_mcps") or []),
        "allowed_skills": list(entry.get("allowed_skills") or []),
        "enabled": bool(entry.get("enabled", True)),
        "created_at": entry.get("created_at") or now,
        "updated_at": entry.get("updated_at") or now,
    }
    if entry.get("last_active_session"):
        result["last_active_session"] = entry["last_active_session"]
    return result


def _load_registry() -> list[dict]:
    if not REGISTRY_FILE.exists():
        return []
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [_normalize_entry(item) for item in data if isinstance(item, dict) and item.get("name")]


def _save_registry(entries: list[dict]) -> None:
    AGENT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _write_agent_config(entry: dict) -> None:
    agent_dir = _ensure_agent_dirs(entry["name"])
    with open(agent_dir / "agent.json", "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)


def _sync_agent_soul(entry: dict) -> None:
    Soul(BASE_PATH, entry["name"]).create_soul(entry.get("soul") or "default")


def ensure_default_agent() -> dict:
    entries = _load_registry()
    if entries:
        for entry in entries:
            _write_agent_config(entry)
        return entries[0]

    entry = _normalize_entry({"name": "Zero", "soul": "default", "enabled": True})
    _ensure_agent_dirs(entry["name"])
    _write_agent_config(entry)
    _sync_agent_soul(entry)
    _save_registry([entry])
    return entry


def list_agents() -> list[dict]:
    entries = _load_registry()
    if not entries:
        entries = [ensure_default_agent()]
    return entries


def get_agent_config(name: str) -> dict | None:
    for entry in list_agents():
        if entry["name"] == name:
            return entry
    config_path = AGENT_ROOT / name / "agent.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("name") == name:
                return _normalize_entry(data)
        except Exception:
            return None
    return None


def create_agent(name: str, soul: str = "default", allowed_mcps: list[str] | None = None, allowed_skills: list[str] | None = None, enabled: bool = True) -> dict:
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("agent 名称不能为空")
    if get_agent_config(cleaned_name):
        raise ValueError(f"agent 已存在: {cleaned_name}")

    entry = _normalize_entry({
        "name": cleaned_name,
        "soul": soul or "default",
        "allowed_mcps": allowed_mcps or [],
        "allowed_skills": allowed_skills or [],
        "enabled": enabled,
    })
    entries = list_agents()
    entries.append(entry)
    _ensure_agent_dirs(cleaned_name)
    _write_agent_config(entry)
    _sync_agent_soul(entry)
    _save_registry(entries)
    return entry


def update_agent_config(name: str, updates: dict) -> dict:
    entries = list_agents()
    target = None
    for entry in entries:
        if entry["name"] == name:
            target = entry
            break
    if target is None:
        raise ValueError(f"agent 不存在: {name}")

    if "soul" in updates and updates["soul"]:
        target["soul"] = updates["soul"]
    if "allowed_mcps" in updates:
        target["allowed_mcps"] = list(updates.get("allowed_mcps") or [])
    if "allowed_skills" in updates:
        target["allowed_skills"] = list(updates.get("allowed_skills") or [])
    if "enabled" in updates:
        target["enabled"] = bool(updates.get("enabled"))
    target["updated_at"] = _now()

    _write_agent_config(target)
    _sync_agent_soul(target)
    _save_registry(entries)
    return target


def delete_agent(name: str) -> None:
    entries = list_agents()
    filtered = [entry for entry in entries if entry["name"] != name]
    if len(filtered) == len(entries):
        raise ValueError(f"agent 不存在: {name}")
    if not filtered:
        raise ValueError("至少保留一个 agent")

    agent_dir = AGENT_ROOT / name
    if agent_dir.exists():
        shutil.rmtree(agent_dir)
    _save_registry(filtered)


def get_agent_names() -> list[str]:
    return [entry["name"] for entry in list_agents() if entry.get("enabled", True)]


def persist_last_active_session(name: str, session_id: str) -> None:
    """把 last_active_session 写入 agent.json 和注册表，供下次启动时做总结用。"""
    entries = list_agents()
    for entry in entries:
        if entry["name"] == name:
            entry["last_active_session"] = session_id
            _write_agent_config(entry)
            _save_registry(entries)
            return

class AgentManager:
    def __init__(self):
        self.AgentMap: dict = {}
        self._tasks: set = set()

    def _get_or_create(self, name: str):
        from .agent import Agent
        if name not in self.AgentMap:
            if get_agent_config(name):
                self.AgentMap[name] = Agent(name)
            else:
                return None
        return self.AgentMap[name]

    def _extract_mentions(self, text: str, all_names: list[str]) -> list[str]:
        if not isinstance(text, str):
            return []
        return [name for name in all_names if f"@{name.lower()}" in text.lower()]

    def _register_task(self, task) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _get_raw_on_event(self, relay_or_event):
        """从 relay 闭包里取回原始 on_event（Flask 队列推送函数）。"""
        return getattr(relay_or_event, "_raw_on_event", relay_or_event)

    async def CallAgent(self, name: str, conv_id: str, message: str, all_members: list[str], on_event=None) -> str:
        agent = self._get_or_create(name)
        if agent is None:
            return ""

        import uuid as _uuid
        turn_key = f"{name}::{_uuid.uuid4().hex[:8]}"

        def relay(event: dict):
            if on_event is None:
                return
            etype = event.get("type")
            d = event.get("data", {})
            base = {"agent_name": name, "turn_key": turn_key}
            if etype == "cycle_message":
                content = d.get("content") or ""
                if content:
                    on_event({"type": "cycle_message", "data": {**base, "content": content,
                                                                "cycle_index": event.get("cycle_index")}})
            elif etype == "tool_call":
                on_event({"type": "tool_call", "data": {**base, **d}})
            elif etype == "tool_result":
                on_event({"type": "tool_result", "data": {**base, **d}})
            elif etype == "final_answer":
                content = d.get("content") or ""
                if content:
                    on_event({"type": "final_answer", "data": {**base, "content": content}})

        # 把原始 on_event 挂在 relay 上，供 @mention 子任务取回
        relay._raw_on_event = on_event

        return await agent.ActiveChat(self, conv_id, message, relay, all_members)

    async def run_group_chat(self, owner_name: str, conv_id: str, message: str, all_members: list[str], on_event=None):
        # 扫描用户消息中的 @mention，对被点名的成员（除群主外）并行触发
        raw_on_event = self._get_raw_on_event(on_event)
        user_mentions = [
            name for name in self._extract_mentions(message, all_members)
            if name != owner_name
        ]
        for name in user_mentions:
            t = asyncio.create_task(self.CallAgent(name, conv_id, None, all_members, raw_on_event))
            self._register_task(t)

        await self.CallAgent(owner_name, conv_id, message, all_members, on_event)
        # 等待 @mention 触发的所有后台 task 完成
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


AGENT_MANAGER = AgentManager()
