"""
agent 管理模块
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

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
    return {
        "name": entry.get("name", ""),
        "soul": entry.get("soul", "default"),
        "allowed_mcps": list(entry.get("allowed_mcps") or []),
        "allowed_skills": list(entry.get("allowed_skills") or []),
        "enabled": bool(entry.get("enabled", True)),
        "created_at": entry.get("created_at") or now,
        "updated_at": entry.get("updated_at") or now,
    }


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
