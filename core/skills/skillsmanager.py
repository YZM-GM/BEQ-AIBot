"""
skills管理模块
"""

from __future__ import annotations

import json
from pathlib import Path

import core.ModelCall.modelcall as mc

CURRENT_DIR = Path(__file__).resolve().parent


def get_sibling_folders(base_path: Path) -> list[str]:
    return [
        f.name
        for f in base_path.iterdir()
        if f.name != "__pycache__" and f.is_dir() and not f.name.startswith('.')
    ]


def _save_skillsinfo(info: dict) -> None:
    with open(CURRENT_DIR / "skillsinfo.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=4)


def _normalize_skill_entry(value) -> dict:
    if isinstance(value, dict):
        return {
            "summary": value.get("summary", ""),
            "enabled": bool(value.get("enabled", True)),
        }
    return {
        "summary": str(value or ""),
        "enabled": True,
    }


def _load_skillsinfo() -> dict:
    if not (CURRENT_DIR / "skillsinfo.json").exists():
        return {}
    with open(CURRENT_DIR / "skillsinfo.json", "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return {}
    return {name: _normalize_skill_entry(value) for name, value in raw.items()}


def registry_skills() -> None:
    skillfolds = get_sibling_folders(CURRENT_DIR)
    skillinfo = _load_skillsinfo()
    changed = False

    for name in skillfolds:
        skillmdpath = CURRENT_DIR / name / "SKILL.md"
        if not skillmdpath.exists():
            continue
        if name in skillinfo:
            continue
        with open(skillmdpath, "r", encoding="utf-8") as f:
            skillmd = f.read()
        summary = mc.BaseModelCall(f"生成这个skill的调用时机说明，什么时候调用，100字以内，输出仅包含这些，不要多余的话，要无格式字符串：{skillmd}")
        skillinfo[name] = {
            "summary": summary or "",
            "enabled": True,
        }
        changed = True

    removed = [name for name in skillinfo.keys() if name not in skillfolds]
    for name in removed:
        skillinfo.pop(name, None)
        changed = True

    if changed:
        _save_skillsinfo(skillinfo)


def get_skillsinfo() -> dict:
    data = _load_skillsinfo()
    if data:
        return data
    registry_skills()
    return _load_skillsinfo()


def list_skills() -> list[dict]:
    return [
        {
            "name": name,
            "summary": meta.get("summary", ""),
            "enabled": bool(meta.get("enabled", True)),
        }
        for name, meta in sorted(get_skillsinfo().items())
    ]


def get_skill_detail(skillname: str) -> dict:
    path, skillmd = get_skillmd(skillname)
    info = get_skillsinfo().get(skillname)
    if info is None:
        raise ValueError(f"skill 不存在: {skillname}")
    return {
        "name": skillname,
        "summary": info.get("summary", ""),
        "enabled": bool(info.get("enabled", True)),
        "path": path,
        "content": skillmd,
    }


def set_skill_enabled(skillname: str, enabled: bool) -> dict:
    skillsinfo = get_skillsinfo()
    if skillname not in skillsinfo:
        raise ValueError(f"skill 不存在: {skillname}")
    skillsinfo[skillname]["enabled"] = bool(enabled)
    _save_skillsinfo(skillsinfo)
    return {
        "name": skillname,
        "summary": skillsinfo[skillname].get("summary", ""),
        "enabled": skillsinfo[skillname].get("enabled", True),
    }


def rescan_skills() -> list[dict]:
    registry_skills()
    return list_skills()


def get_skillmd(skillname: str):
    skillpath = CURRENT_DIR / skillname
    if not skillpath.exists():
        return None, None
    with open(skillpath / "SKILL.md", "r", encoding="utf-8") as f:
        skillmd = f.read()
    return str(skillpath), skillmd
