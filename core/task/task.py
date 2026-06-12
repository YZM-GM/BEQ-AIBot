"""
任务模块 — 以 conversation_id 为键的字典存储
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

import core.ModelCall as mc


class Task:
    def __init__(self, basepath, name: str):
        self.task_dir = basepath / "core" / "agent" / name / "task"
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.task_file = self.task_dir / "tasks.json"
        self._store: dict[str, list[dict]] = self._load()

    def _load(self) -> dict[str, list[dict]]:
        if self.task_file.exists():
            try:
                with open(self.task_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
                # 兼容旧版 list 格式：迁移到 "default" 键
                if isinstance(data, list):
                    return {"default": data}
            except Exception:
                pass
        with open(self.task_file, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
        return {}

    def _save(self) -> None:
        with open(self.task_file, "w", encoding="utf-8") as f:
            json.dump(self._store, f, ensure_ascii=False, indent=2)

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _key(self, conversation_id: str | None) -> str:
        return conversation_id or "default"

    # ── 写入 ──────────────────────────────────────────────────────────────

    def apply_tasks(self, tasks: list[str], conversation_id: str | None = None, source: str = "tool") -> None:
        now = self._now()
        key = self._key(conversation_id)
        normalized = []
        for title in tasks:
            if not isinstance(title, str):
                continue
            text = title.strip()
            if not text:
                continue
            normalized.append({
                "id": f"task-{uuid.uuid4()}",
                "title": text,
                "status": "pending",
                "created_at": now,
                "updated_at": now,
                "source": source,
                "notes": "",
            })
        self._store[key] = normalized
        self._save()

    def update_task_status(self, task_ids: list[str], status: str, conversation_id: str | None = None) -> None:
        if not task_ids:
            return
        key = self._key(conversation_id)
        tasks = self._store.get(key, [])
        now = self._now()
        ids = set(task_ids)
        updated = False
        for task in tasks:
            if task.get("id") in ids:
                task["status"] = status
                task["updated_at"] = now
                updated = True
        if updated:
            self._store[key] = tasks
            self._save()

    # ── 读取 ──────────────────────────────────────────────────────────────

    def GetTasks(self, conversation_id: str | None = None) -> list[dict]:
        return self._store.get(self._key(conversation_id), [])

    def GetOpenTasks(self, conversation_id: str | None = None) -> list[dict]:
        return [t for t in self.GetTasks(conversation_id) if t.get("status") not in {"completed", "failed", "cancelled"}]

    def format_for_prompt(self, conversation_id: str | None = None) -> str:
        tasks = self.GetTasks(conversation_id)
        if not tasks:
            return "当前没有任务。"
        lines = ["当前任务状态："]
        for task in tasks:
            lines.append(f"- [{task.get('status', 'pending')}] {task.get('id', '')}: {task.get('title', '')}")
        return "\n".join(lines)

    def check_complete(self, messages: list[dict], conversation_id: str | None = None) -> bool:
        open_tasks = self.GetOpenTasks(conversation_id)
        if not open_tasks:
            return True

        task_lines = "\n".join(
            f"- id={t['id']} | title={t['title']} | status={t['status']}"
            for t in open_tasks
        )
        prompt = (
            "请根据当前上下文判断下面哪些任务已经完成。"
            "只允许返回严格 JSON，格式为："
            '{"completed_ids": ["task-1", "task-2"]}'
            "。如果都没完成，返回 {\"completed_ids\": []}。\n\n"
            f"待判断任务：\n{task_lines}"
        )

        res = mc.step_model_call(messages + [{"role": "user", "content": prompt}])
        try:
            content = res.get("assistant_message", {}).get("content") or "{}"
            parsed = json.loads(content)
            completed_ids = parsed.get("completed_ids", [])
            if not isinstance(completed_ids, list):
                completed_ids = []
            completed_ids = [tid for tid in completed_ids if isinstance(tid, str)]
            self.update_task_status(completed_ids, "completed", conversation_id)
        except Exception:
            return False

        return not self.GetOpenTasks(conversation_id)
