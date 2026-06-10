"""
群聊运行时编排
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from core.agent.agent import Agent
from core.agent.agentmanager import get_agent_config
from core.chat.chatmanager import get_conversation, update_conversation

EventCallback = Callable[[dict], None]


@dataclass
class AgentLease:
    agent_name: str
    conversation_id: str
    task_id: str
    role: str
    status: str = "running"
    queued_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class AgentScheduler:
    def __init__(self):
        self.active: dict[str, AgentLease] = {}
        self.waiting: dict[str, deque[AgentLease]] = defaultdict(deque)

    def try_acquire(self, agent_name: str, conversation_id: str, task_id: str, role: str) -> tuple[str, AgentLease]:
        current = self.active.get(agent_name)
        lease = AgentLease(agent_name=agent_name, conversation_id=conversation_id, task_id=task_id, role=role)
        if current is None:
            self.active[agent_name] = lease
            return "running", lease
        self.waiting[agent_name].append(lease)
        lease.status = "queued"
        return "queued", lease

    def release(self, agent_name: str) -> AgentLease | None:
        self.active.pop(agent_name, None)
        queue = self.waiting.get(agent_name)
        if not queue:
            return None
        next_lease = queue.popleft()
        next_lease.status = "running"
        self.active[agent_name] = next_lease
        if not queue:
            self.waiting.pop(agent_name, None)
        return next_lease

    def snapshot(self) -> list[dict]:
        rows = []
        for lease in self.active.values():
            rows.append(
                {
                    "agent_name": lease.agent_name,
                    "conversation_id": lease.conversation_id,
                    "task_id": lease.task_id,
                    "role": lease.role,
                    "status": lease.status,
                }
            )
        for agent_name, queue in self.waiting.items():
            for lease in queue:
                rows.append(
                    {
                        "agent_name": agent_name,
                        "conversation_id": lease.conversation_id,
                        "task_id": lease.task_id,
                        "role": lease.role,
                        "status": lease.status,
                    }
                )
        return rows


SCHEDULER = AgentScheduler()


class GroupChatRunner:
    def __init__(self, conversation_id: str):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"conversation 不存在: {conversation_id}")
        if conversation.get("type") != "group":
            raise ValueError("仅 group conversation 支持 GroupChatRunner")
        self.conversation = conversation
        self.owner_name = conversation.get("owner_agent") or ""
        self.members = [name for name in conversation.get("member_agents") or [] if name != self.owner_name]
        self.group_turn_id = f"gturn-{uuid.uuid4()}"
        self.task_board: list[dict] = []

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _emit(self, on_event: EventCallback | None, event_type: str, **data):
        if on_event is None:
            return
        on_event(
            {
                "type": event_type,
                "conversation_id": self.conversation["id"],
                "group_turn_id": self.group_turn_id,
                "data": data,
            }
        )

    def _persist_event(self, payload: dict):
        participant_names = [self.owner_name, *self.members]
        for agent_name in participant_names:
            if not agent_name:
                continue
            agent = Agent(agent_name)
            event = {
                "role": payload.get("role", "user"),
                "content": payload.get("content", ""),
                "kind": payload.get("kind", "group_event"),
                "conversation_id": self.conversation["id"],
                "chat_type": "group",
                "group_turn_id": self.group_turn_id,
                "speaker": payload.get("speaker", ""),
                "source_agent": payload.get("source_agent", ""),
                "target_agent": payload.get("target_agent", ""),
                "task_id": payload.get("task_id", ""),
                "timestamp": self._now(),
            }
            agent.memory.add_session_event(event)

    async def _run_agent(self, agent_name: str, message: str, task_id: str, role: str, on_event: EventCallback | None) -> str:
        status, lease = SCHEDULER.try_acquire(agent_name, self.conversation["id"], task_id, role)
        self._emit(on_event, "group_status", agent_name=agent_name, task_id=task_id, status=status, role=role)
        self._persist_event(
            {
                "role": "user",
                "content": f"[{role}] {agent_name} {status}",
                "kind": "group_status",
                "speaker": agent_name,
                "source_agent": agent_name,
                "task_id": task_id,
            }
        )
        if status == "queued":
            return f"{agent_name} 当前忙碌，已进入等待队列。"

        agent = Agent(agent_name)
        collected: list[str] = []

        def relay(event: dict):
            event_type = event.get("type")
            if event_type == "cycle_message":
                content = event.get("data", {}).get("content") or event.get("message", "")
                collected.append(content)
                self._emit(on_event, "agent_message", agent_name=agent_name, content=content, task_id=task_id, role=role)
                self._persist_event(
                    {
                        "role": "assistant" if agent_name == self.owner_name else "user",
                        "content": content,
                        "kind": "agent_message",
                        "speaker": agent_name,
                        "source_agent": agent_name,
                        "task_id": task_id,
                    }
                )
            elif event_type == "tool_call":
                self._emit(on_event, "tool_call", agent_name=agent_name, tool_name=event.get("data", {}).get("tool_name", ""), arguments=event.get("data", {}).get("arguments", {}), task_id=task_id, role=role)
            elif event_type == "tool_result":
                self._emit(on_event, "tool_result", agent_name=agent_name, tool_name=event.get("data", {}).get("tool_name", ""), result=event.get("data", {}).get("result", ""), task_id=task_id, role=role)
            elif event_type == "final_answer":
                content = event.get("data", {}).get("content") or ""
                if content:
                    collected.append(content)
                    self._emit(on_event, "agent_message", agent_name=agent_name, content=content, task_id=task_id, role=role)
                    self._persist_event(
                        {
                            "role": "assistant" if agent_name == self.owner_name else "user",
                            "content": content,
                            "kind": "agent_message",
                            "speaker": agent_name,
                            "source_agent": agent_name,
                            "task_id": task_id,
                        }
                    )

        try:
            await agent.chat(message, on_event=relay)
        finally:
            next_lease = SCHEDULER.release(agent_name)
            self._emit(on_event, "group_status", agent_name=agent_name, task_id=task_id, status="completed", role=role)
            if next_lease is not None:
                self._emit(on_event, "group_status", agent_name=next_lease.agent_name, task_id=next_lease.task_id, status="running", role=next_lease.role)
        return "\n".join([text for text in collected if text]).strip()

    def _build_task_board(self, user_message: str) -> list[dict]:
        members = self.members or [self.owner_name]
        tasks = [
            {
                "id": f"task-{uuid.uuid4()}",
                "title": f"分析用户需求：{user_message[:40]}",
                "assignee": self.owner_name,
                "status": "running",
                "progress_note": "群主正在拆解任务",
                "updated_at": self._now(),
            }
        ]
        for member_name in members:
            tasks.append(
                {
                    "id": f"task-{uuid.uuid4()}",
                    "title": f"成员执行子任务：{member_name}",
                    "assignee": member_name,
                    "status": "pending",
                    "progress_note": "等待群主分配",
                    "updated_at": self._now(),
                }
            )
        return tasks

    def _set_task_status(self, task_id: str, status: str, progress_note: str):
        for task in self.task_board:
            if task["id"] != task_id:
                continue
            task["status"] = status
            task["progress_note"] = progress_note
            task["updated_at"] = self._now()
            return

    async def run(self, message: str, on_event: EventCallback | None = None) -> dict:
        if not get_agent_config(self.owner_name):
            raise ValueError(f"群主 agent 不存在: {self.owner_name}")

        self.task_board = self._build_task_board(message)
        self._emit(on_event, "conversation_meta", conversation=self.conversation, scheduler=SCHEDULER.snapshot())
        self._emit(on_event, "task_board", tasks=self.task_board)

        owner_task = self.task_board[0]
        owner_prompt = (
            "你是群聊群主。请接收用户命令，先给出任务拆解、成员分工、监控计划，再在后续根据成员结果汇总。"
            f"\n用户命令：{message}"
            f"\n成员：{json.dumps(self.members, ensure_ascii=False)}"
        )
        owner_result = await self._run_agent(self.owner_name, owner_prompt, owner_task["id"], "owner", on_event)
        self._set_task_status(owner_task["id"], "completed", "群主已完成任务拆解")
        self._emit(on_event, "task_board", tasks=self.task_board)

        member_results = []
        for task in self.task_board[1:]:
            assignee = task["assignee"]
            self._set_task_status(task["id"], "running", "成员正在执行")
            self._emit(on_event, "task_board", tasks=self.task_board)
            member_prompt = (
                "你正在参与一个 agent 群聊，请完成群主分配给你的子任务，并简洁返回执行结果。"
                f"\n群主拆解：{owner_result or message}"
                f"\n你的身份：{assignee}"
            )
            result = await self._run_agent(assignee, member_prompt, task["id"], "member", on_event)
            status = "completed" if result and "等待队列" not in result else "blocked"
            progress_note = result[:120] if result else "未返回结果"
            self._set_task_status(task["id"], status, progress_note)
            member_results.append({"agent": assignee, "content": result})
            self._emit(on_event, "task_board", tasks=self.task_board)

        summary_task_id = f"task-{uuid.uuid4()}"
        status, _ = SCHEDULER.try_acquire(self.owner_name, self.conversation["id"], summary_task_id, "owner")
        self._emit(on_event, "group_status", agent_name=self.owner_name, task_id=summary_task_id, status=status, role="owner")
        if status == "queued":
            summary_result = "群主仍在忙碌，最终总结已排队。"
        else:
            try:
                owner = Agent(self.owner_name)
                followup = (
                    "你是群聊群主，请根据任务拆解和成员反馈给出最终总结，并说明任务完成情况。"
                    f"\n初始拆解：{owner_result}"
                    f"\n成员反馈：{json.dumps(member_results, ensure_ascii=False)}"
                    f"\n任务板：{json.dumps(self.task_board, ensure_ascii=False)}"
                )
                captured: list[str] = []

                def relay(event: dict):
                    event_type = event.get("type")
                    if event_type == "cycle_message":
                        content = event.get("data", {}).get("content") or event.get("message", "")
                        if content:
                            captured.append(content)
                            self._emit(on_event, "agent_message", agent_name=self.owner_name, content=content, task_id=summary_task_id, role="owner")
                    elif event_type == "tool_call":
                        self._emit(on_event, "tool_call", agent_name=self.owner_name, tool_name=event.get("data", {}).get("tool_name", ""), arguments=event.get("data", {}).get("arguments", {}), task_id=summary_task_id, role="owner")
                    elif event_type == "tool_result":
                        self._emit(on_event, "tool_result", agent_name=self.owner_name, tool_name=event.get("data", {}).get("tool_name", ""), result=event.get("data", {}).get("result", ""), task_id=summary_task_id, role="owner")
                    elif event_type == "final_answer":
                        content = event.get("data", {}).get("content") or ""
                        if content:
                            captured.append(content)
                            self._emit(on_event, "agent_message", agent_name=self.owner_name, content=content, task_id=summary_task_id, role="owner")

                await owner.chat(followup, on_event=relay)
                summary_result = "\n".join([text for text in captured if text]).strip()
            finally:
                SCHEDULER.release(self.owner_name)
                self._emit(on_event, "group_status", agent_name=self.owner_name, task_id=summary_task_id, status="completed", role="owner")

        for task in self.task_board:
            if task["status"] == "running":
                self._set_task_status(task["id"], "completed", task["progress_note"] or "已完成")
        self._emit(on_event, "task_board", tasks=self.task_board)
        self._persist_event(
            {
                "role": "assistant",
                "content": summary_result,
                "kind": "final_answer",
                "speaker": self.owner_name,
                "source_agent": self.owner_name,
            }
        )
        update_conversation(self.conversation["id"], last_message_preview=(summary_result or message)[:100])
        self._emit(on_event, "final_answer", content=summary_result, task_board=self.task_board)
        return {
            "conversation_id": self.conversation["id"],
            "group_turn_id": self.group_turn_id,
            "content": summary_result,
            "tasks": self.task_board,
        }
