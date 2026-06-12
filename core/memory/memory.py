"""
记忆管理模块

附加到agent上使用，记忆存储地方应当在agent抽象类里
"""

import json
from pathlib import Path
import datetime

from core.ModelCall import BaseModelCall


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.datetime.now().date().isoformat()


class Memory:
    def __init__(self, basepath, name: str):
        self.memory_path = basepath / "core" / "agent" / name / "memory"
        self.session_memory_filepath = self.memory_path / "sessions"
        self.diary_memory_filepath = self.memory_path / "diary.json"
        self.longterm_memory_filepath = self.memory_path / "longterm.json"
        self.session_memory_filepath.mkdir(parents=True, exist_ok=True)
        self.diary_memory = self._load_diary_memory()
        self.longterm_memory = self._load_longterm_memory()

    def _session_file(self, session_id: str) -> Path:
        safe_name = (session_id or "default").replace("/", "_").replace("\\", "_")
        return self.session_memory_filepath / f"{safe_name}.json"

    def list_session_ids(self) -> list[str]:
        return sorted(path.stem for path in self.session_memory_filepath.glob("*.json"))

    def load_session_memory(self, session_id: str) -> list:
        session_file = self._session_file(session_id)
        if session_file.exists():
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return []

    def _save_session_memory(self, session_id: str, records: list[dict]) -> None:
        with open(self._session_file(session_id), "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    def _load_longterm_memory(self) -> list:
        if self.longterm_memory_filepath.exists():
            with open(self.longterm_memory_filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []

        with open(self.longterm_memory_filepath, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return []

    def _save_longterm_memory(self) -> None:
        with open(self.longterm_memory_filepath, "w", encoding="utf-8") as f:
            json.dump(self.longterm_memory, f, ensure_ascii=False, indent=2)

    def add_longterm_memory(self, mem:str) -> None:
        self.longterm_memory.append(mem)
        self._save_longterm_memory()

    def _load_diary_memory(self) -> list:
        if self.diary_memory_filepath.exists():
            with open(self.diary_memory_filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []

        with open(self.diary_memory_filepath, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return []

    def _save_diary_memory(self) -> None:
        with open(self.diary_memory_filepath, "w", encoding="utf-8") as f:
            json.dump(self.diary_memory, f, ensure_ascii=False, indent=2)

    def _make_session_id(self, conversation_id: str | None = None, day: str | None = None) -> str:
        return f"{conversation_id or 'default'}__{day or _today()}"

    def _event_day(self, event: dict) -> str:
        timestamp = str(event.get("timestamp") or _now())
        return timestamp.split("T", 1)[0]

    def add_session_memory(self, role: str, content: str, turn_id: str | None = None, cycle_index: int | None = None, kind: str = "message", conversation_id: str | None = None, session_id: str | None = None, **extra):
        event = {
            "role": role,
            "content": content,
            "kind": kind,
            "timestamp": extra.pop("timestamp", _now()),
            "conversation_id": conversation_id or extra.get("conversation_id") or "default",
        }
        if turn_id is not None:
            event["turn_id"] = turn_id
        if cycle_index is not None:
            event["cycle_index"] = cycle_index
        event.update(extra)
        self.add_session_event(event, session_id=session_id)

    def add_session_event(self, event: dict, session_id: str | None = None) -> None:
        timestamp = event.get("timestamp") or _now()
        event["timestamp"] = timestamp
        conversation_id = event.get("conversation_id") or "default"
        target_session_id = session_id or event.get("session_id") or self._make_session_id(conversation_id=conversation_id, day=str(timestamp).split("T", 1)[0])
        event["session_id"] = target_session_id
        records = self.load_session_memory(target_session_id)
        records.append(event)
        self._save_session_memory(target_session_id, records)

    def summary_session_memory(self, session_id: str) -> str:
        session_data = self.load_session_memory(session_id)
        if not session_data:
            return ""

        session_text = ""
        for item in session_data:
            speaker = item.get("speaker") or item.get("role") or "unknown"
            session_text += f"{speaker}: {item.get('content', '')}\n"

        day = session_id.rsplit("__", 1)[-1] if "__" in session_id else _today()
        existing = next((item for item in self.diary_memory if item.get("date") == day and item.get("session_id") == session_id), None)
        if existing:
            content = f"请你总结这段对话的主要内容，给出精简的总结但是不遗漏重要信息：全部上下文是{session_text}，上一版总结是{existing.get('summary', '')}。返回格式严格仅为一个无格式中文字符串"
        else:
            content = f"请你总结这段对话的主要内容，给出精简的总结但是不遗漏重要信息：全部上下文是{session_text}。返回格式严格仅为一个无格式中文字符串"

        summary = BaseModelCall(content) or ""
        payload = {
            "date": day,
            "session_id": session_id,
            "summary": summary,
        }
        if existing is None:
            self.diary_memory.append(payload)
        else:
            existing.update(payload)
        self._save_diary_memory()
        return summary

    def flush_session_to_diary(self, session_id: str) -> str:
        summary = self.summary_session_memory(session_id)
        session_file = self._session_file(session_id)
        if session_file.exists():
            session_file.unlink()
        return summary

    async def flush_session_to_diary_async(self, session_id: str) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.flush_session_to_diary, session_id)

    def maybe_rollover_session(self, conversation_id: str, session_id: str | None = None) -> str | None:
        target_session = session_id or self._make_session_id(conversation_id=conversation_id)
        records = self.load_session_memory(target_session)
        if not records:
            return None
        last_day = self._event_day(records[-1])
        if last_day != _today():
            return self.flush_session_to_diary(target_session)
        if len(records) >= 80:
            return self.flush_session_to_diary(target_session)
        return None

    def close_conversation(self, conversation_id: str) -> str | None:
        matched = [session_id for session_id in self.list_session_ids() if session_id.startswith(f"{conversation_id}__")]
        if not matched:
            return None
        latest = sorted(matched)[-1]
        return self.flush_session_to_diary(latest)

    def GetMemory(self, conversation_id: str | None = None, current_agent: str | None = None) -> list[dict]:
        messages: list[dict] = []

        # 长期记忆和 diary 全量载入
        longterm_scope = self._load_longterm_memory()
        diary_scope = self._load_diary_memory()
        messages.append({"role": "system", "content": "这些是你的长期记忆：" + json.dumps(longterm_scope, ensure_ascii=False)})
        messages.append({"role": "system", "content": "这些是从你创建开始我们聊过内容的聊天概括：" + json.dumps(diary_scope, ensure_ascii=False)})

        # session 记忆只载入当前会话，取最近 80 条
        session_ids = self.list_session_ids()
        if conversation_id is not None:
            session_ids = [sid for sid in session_ids if sid.startswith(f"{conversation_id}__")]
        session_ids = sorted(session_ids)
        session_records: list[dict] = []
        for session_id in session_ids:
            session_records.extend(self.load_session_memory(session_id))
        session_records = session_records[-80:]

        for item in session_records:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if content is None:
                continue
            role = item.get("role")
            speaker = item.get("speaker") or item.get("source_agent")
            if current_agent and speaker and speaker != current_agent and role == "assistant":
                role = "user"
            if role not in {"user", "assistant", "tool"}:
                role = "user"
            message = {
                "role": role,
                "content": content,
            }
            tool_call_id = item.get("tool_call_id")
            if role == "tool" and tool_call_id:
                message["tool_call_id"] = tool_call_id
            messages.append(message)
        return messages
