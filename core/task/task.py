"""
任务模块

完成一整个任务安排执行反馈流程
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
        self.group_task_file = self.task_dir / "group_tasks.json"
        self.tasks = self._load_tasks(self.task_file)
        self.group_tasks = self._load_tasks(self.group_task_file)

    def _load_tasks(self, path: Path) -> list[dict]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
            except Exception:
                pass

        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return []

    def _save_tasks(self, path: Path, tasks: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def apply_tasks(self, tasks: list[str], source: str = "tool"):
        now = self._now()
        normalized = []
        for title in tasks:
            if not isinstance(title, str):
                continue
            text = title.strip()
            if not text:
                continue
            normalized.append(
                {
                    "id": f"task-{uuid.uuid4()}",
                    "title": text,
                    "status": "pending",
                    "created_at": now,
                    "updated_at": now,
                    "source": source,
                    "notes": "",
                }
            )
        self.tasks = normalized
        self._save_tasks(self.task_file, self.tasks)

    def set_group_tasks(self, conversation_id: str, tasks: list[dict]) -> None:
        normalized = []
        now = self._now()
        for task in tasks:
            if not isinstance(task, dict):
                continue
            normalized.append(
                {
                    "id": task.get("id") or f"task-{uuid.uuid4()}",
                    "conversation_id": conversation_id,
                    "title": task.get("title", ""),
                    "assignee": task.get("assignee", ""),
                    "status": task.get("status", "pending"),
                    "progress_note": task.get("progress_note", ""),
                    "created_at": task.get("created_at", now),
                    "updated_at": task.get("updated_at", now),
                }
            )
        self.group_tasks = [task for task in self.group_tasks if task.get("conversation_id") != conversation_id] + normalized
        self._save_tasks(self.group_task_file, self.group_tasks)

    def get_group_tasks(self, conversation_id: str) -> list[dict]:
        return [task for task in self.group_tasks if task.get("conversation_id") == conversation_id]

    def GetTasks(self) -> list[dict]:
        return self.tasks

    def GetOpenTasks(self) -> list[dict]:
        return [task for task in self.tasks if task.get("status") not in {"completed", "failed", "cancelled"}]

    def format_for_prompt(self) -> str:
        if not self.tasks:
            return "当前没有任务。"

        lines = ["当前任务状态："]
        for task in self.tasks:
            lines.append(f"- [{task.get('status', 'pending')}] {task.get('id', '')}: {task.get('title', '')}")
        return "\n".join(lines)

    def update_task_status(self, task_ids: list[str], status: str) -> None:
        if not task_ids:
            return
        now = self._now()
        updated = False
        ids = set(task_ids)
        for task in self.tasks:
            if task.get("id") in ids:
                task["status"] = status
                task["updated_at"] = now
                updated = True
        if updated:
            self._save_tasks(self.task_file, self.tasks)

    def check_complete(self, messages: list[dict]) -> bool:
        open_tasks = self.GetOpenTasks()
        if not open_tasks:
            return True

        task_lines = "\n".join(
            f"- id={task['id']} | title={task['title']} | status={task['status']}"
            for task in open_tasks
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
            completed_ids = [task_id for task_id in completed_ids if isinstance(task_id, str)]
            self.update_task_status(completed_ids, "completed")
        except Exception:
            return False

        return not self.GetOpenTasks()
