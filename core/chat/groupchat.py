"""
群聊入口：同步群聊记忆后唤起群主，后续流转由 AgentManager 负责
"""

from __future__ import annotations

from typing import Callable

from core.agent.agentmanager import get_agent_config, AGENT_MANAGER
from core.chat.chatmanager import get_conversation, update_conversation
from core.memory.memory import Memory
from pathlib import Path

BASE_PATH = Path(__file__).resolve().parent.parent.parent
EventCallback = Callable[[dict], None]


class GroupChatRunner:
    def __init__(self, conversation_id: str):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"conversation 不存在: {conversation_id}")
        if conversation.get("type") != "group":
            raise ValueError("仅 group conversation 支持 GroupChatRunner")
        self.conversation = conversation
        self.conv_id = conversation_id
        self.owner_name: str = conversation.get("owner_agent") or ""
        self.all_members: list[str] = list(conversation.get("member_agents") or [])

    def _sync_user_message(self, message: str):
        """把用户消息写入所有成员的会话记忆"""
        for name in self.all_members:
            mem = Memory(BASE_PATH, name)
            mem.add_session_memory(
                role="user",
                content=message,
                kind="user_message",
                conversation_id=self.conv_id,
                speaker="user",
                source_agent="user",
            )

    async def run(self, message: str, on_event: EventCallback | None = None, team_mode: bool = False) -> dict:
        if not get_agent_config(self.owner_name):
            raise ValueError(f"群主 agent 不存在: {self.owner_name}")

        self._sync_user_message(message)

        if team_mode:
            actual_message = (
                "你是群聊群主，负责统筹协调。请接收用户命令并给出详细的任务分工计划。\n"
                "你只负责安排工作，不参与具体工作。说明每个成员应做什么，以及谁先开始执行。\n"
                "在计划末尾用 @成员名 点名可以立刻开始工作的成员。\n"
                "命令成员完成自己的工作后@下一步交接的成员\n"
                "严格要求组员调用先group-member Skill"
                f"用户命令：{message}\n"
                f"群成员列表：{self.all_members}"
            )
        else:
            actual_message = message

        await AGENT_MANAGER.run_group_chat(
            owner_name=self.owner_name,
            conv_id=self.conv_id,
            message=actual_message,
            all_members=self.all_members,
            on_event=on_event,
        )

        update_conversation(self.conv_id, last_message_preview=message[:100])
        return {
            "conversation_id": self.conv_id,
            "content": "群聊任务已完成",
        }
