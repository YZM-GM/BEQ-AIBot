"""
soul 管理模块
"""

from __future__ import annotations

import json
from pathlib import Path

SOUL_DIR = Path(__file__).resolve().parent / "souls"


def _soul_file(name: str) -> Path:
    return SOUL_DIR / f"{name}.json"


def list_souls() -> list[dict]:
    SOUL_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(SOUL_DIR.glob("*.json")):
        content = get_soul(path.stem)
        items.append(
            {
                "name": path.stem,
                "content": content,
                "preview": str(content)[:120],
            }
        )
    return items


def get_soul(name: str):
    path = _soul_file(name)
    if not path.exists():
        raise ValueError(f"soul 不存在: {name}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_soul(name: str, content) -> dict:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("soul 名称不能为空")
    path = _soul_file(cleaned)
    if path.exists():
        raise ValueError(f"soul 已存在: {cleaned}")
    SOUL_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    return {"name": cleaned, "content": content, "preview": str(content)[:120]}


def update_soul(name: str, content) -> dict:
    path = _soul_file(name)
    if not path.exists():
        raise ValueError(f"soul 不存在: {name}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    return {"name": name, "content": content, "preview": str(content)[:120]}


def delete_soul(name: str) -> None:
    path = _soul_file(name)
    if not path.exists():
        raise ValueError(f"soul 不存在: {name}")
    path.unlink()
