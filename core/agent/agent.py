"""
设计agent抽象类的地方，应当抽象成一个具备完整人格的ai智能体
agent抽象类的所有数据：记忆，人格等存储在data文件夹内
存储时以一个完整agent来存储读取
"""

import json
import uuid

import asyncio

from pathlib import Path

from core.memory.memory import Memory
from core.mcp.MCPs import MCPs
from core.mcp.toolregistry import execute_tool
from core.ModelCall.modelcall import step_model_call_async
from core.soul.soul import Soul
from core.task.task import Task
from core.skills.skills import Skills

from .agentmanager import AgentManager, persist_last_active_session
from datetime import datetime

BASE_PATH = Path(__file__).resolve().parent.parent.parent


class Agent:
    def __init__(self, name):
        self.name = name

        agentpath = BASE_PATH / "core" / "agent" / name
        if not agentpath.exists():
            (agentpath / "memory").mkdir(parents=True, exist_ok=True)
            (agentpath / "soul").mkdir(parents=True, exist_ok=True)
            (agentpath / "memory" / "sessions").mkdir(parents=True, exist_ok=True)
            (agentpath / "task").mkdir(parents=True, exist_ok=True)

        from core.agent.agentmanager import ensure_default_agent, get_agent_config

        self.config = get_agent_config(name) or ensure_default_agent()
        self.memory = Memory(BASE_PATH, name)
        self.soul = Soul(BASE_PATH, name)
        self.mcps = MCPs(self.config.get("allowed_mcps") or None)
        self.task = Task(BASE_PATH, name)
        self.skill = Skills(BASE_PATH, self.config.get("allowed_skills") or None)
        self.current_conversation_id: str | None = None

        self.becalled = []
        self.isavaliable = True

        # 上次活跃会话（从 agent.json 恢复，启动时用于补做总结）
        self._last_active_session: str | None = self.config.get("last_active_session")

        print(f"初始化Agent--{name}\n")

    def _system_prompt(self, conversation_id: str | None = None) -> str:
        soul_text = self.soul.GetSoul()
        skills_text = self.skill.GetSkills()
        tasks_text = self.task.format_for_prompt(conversation_id)
        return f"名字:{self.name}\n{soul_text}\n Skills:\n{skills_text}\n当前任务：\n{tasks_text}"

    def _build_messages(self, conversation_id: str | None = None) -> list[dict]:
        return [
            {"role": "system", "content": self._system_prompt(conversation_id)},
            *self.memory.GetMemory(conversation_id=conversation_id, current_agent=self.name),
        ]

    async def chat(self, message: str, on_event=None, max_cycles: int = 20, conversation_id: str | None = None) -> dict:
        turn_id = str(uuid.uuid4())
        tool_trace = []
        usage = {}
        model = ""
        final_content = ""
        conversation_key = conversation_id or "default"
        self.current_conversation_id = conversation_key

        current_session_id = self.memory._make_session_id(conversation_id=conversation_key)

        prev_session = self._last_active_session
        if prev_session and prev_session != current_session_id:
            prev_file = self.memory._session_file(prev_session)
            if prev_file.exists():
                print(f"[{self.name}] session {prev_session} → diary")
                await self.memory.flush_session_to_diary_async(prev_session)
            self._last_active_session = None

        self.memory.maybe_rollover_session(conversation_key)

        if self._last_active_session != current_session_id:
            self._last_active_session = current_session_id
            persist_last_active_session(self.name, current_session_id)

        def emit(event_type: str, cycle_index: int | None = None, message_text: str = "", data=None):
            if on_event is None:
                return
            payload = {
                "turn_id": turn_id,
                "cycle_index": cycle_index,
                "type": event_type,
                "message": message_text,
                "data": data or {},
                "conversation_id": conversation_key,
            }
            on_event(payload)

        emit("turn_start", message_text="收到用户消息")
        if message:
            self.memory.add_session_memory("user", message, turn_id=turn_id, cycle_index=0, kind="user_message", conversation_id=conversation_key, speaker="user", source_agent="user")

        for cycle_index in range(1, max_cycles + 1):
            emit("cycle_start", cycle_index, f"开始第 {cycle_index} 轮思考")
            messages = self._build_messages(conversation_id=conversation_key)

            print(f"{datetime.now()} {self.name} call API")

            step = await step_model_call_async(messages, self.mcps.toollist)
            model = step["model"]
            usage = step["usage"]
            assistant_message = step.get("assistant_message", {})
            tool_calls = assistant_message.get("tool_calls", []) or []
            assistant_content = assistant_message.get("content") or ""

            if assistant_content:
                self.memory.add_session_memory(
                    "assistant",
                    assistant_content,
                    turn_id=turn_id,
                    cycle_index=cycle_index,
                    kind="cycle_message",
                    conversation_id=conversation_key,
                    speaker=self.name,
                    source_agent=self.name,
                )
                emit(
                    "cycle_message",
                    cycle_index,
                    "agent 在本轮发言",
                    {"content": assistant_content},
                )

            if tool_calls:
                emit("decision", cycle_index, "agent 决定先调用工具")
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    arguments_text = fn.get("arguments", "{}")

                    try:
                        args = json.loads(arguments_text)
                    except Exception:
                        args = {}

                    emit(
                        "tool_call",
                        cycle_index,
                        f"调用工具 {tool_name}",
                        {"tool_name": tool_name, "arguments": args},
                    )
                    result = await execute_tool(self, tool_name, args)

                    self.memory.add_session_memory(
                        "tool",
                        result,
                        turn_id=turn_id,
                        cycle_index=cycle_index,
                        kind="tool_result",
                        tool_name=tool_name,
                        tool_input=arguments_text,
                        tool_output=result,
                        tool_call_id=tc.get("id", ""),
                        conversation_id=conversation_key,
                        speaker=self.name,
                        source_agent=self.name,
                    )

                    preview = result[:800]
                    emit(
                        "tool_result",
                        cycle_index,
                        f"工具 {tool_name} 已返回结果",
                        {"tool_name": tool_name, "result": preview},
                    )
                    tool_trace.append({"tool": tool_name, "args": args, "result": result})
                continue

            final_content = assistant_content
            emit(
                "final_answer",
                cycle_index,
                "agent 给出了最终回答",
                {"model": model, "content": final_content, "usage": usage},
            )
            break
        else:
            final_content = "已达到最大思考轮数，停止继续调用工具。"
            self.memory.add_session_memory(
                "assistant",
                final_content,
                turn_id=turn_id,
                cycle_index=max_cycles,
                kind="final_answer",
                conversation_id=conversation_key,
                speaker=self.name,
                source_agent=self.name,
            )
            emit("error", max_cycles, final_content)

        emit("turn_end", message_text="本轮对话结束")
        return {
            "turn_id": turn_id,
            "model": model,
            "content": final_content,
            "usage": usage,
            "tool_trace": tool_trace,
            "conversation_id": conversation_key,
        }

    async def ActiveChat(self, agentmanager, conversationid: str, message: str, on_event=None, group_members: list | None = None) -> str:
        if self.isavaliable:
            self.isavaliable = False
            self.becalled.append([conversationid, message, on_event, group_members])
            final_content = ""

            try:
                while self.becalled:
                    info_conv, info_msg, info_evt, info_members = self.becalled.pop(0)
                    result = await self.chat(info_msg, on_event=info_evt, conversation_id=info_conv)
                    final_content = result.get("content", "")

                    if info_members and final_content:
                        for member_name in info_members:
                            if member_name == self.name:
                                continue
                            member_memory = Memory(BASE_PATH, member_name)
                            member_memory.add_session_memory(
                                role="user",
                                content=f"[{self.name}]: {final_content}",
                                kind="group_message",
                                conversation_id=info_conv,
                                speaker=self.name,
                                source_agent=self.name,
                            )

                    raw_on_event = agentmanager._get_raw_on_event(info_evt)
                    for next_name in agentmanager._extract_mentions(final_content, info_members or []):
                        if next_name == self.name: continue
                        print(f"{self.name} call {next_name}")
                        t = asyncio.create_task(agentmanager.CallAgent(next_name, info_conv, None, info_members, raw_on_event))
                        agentmanager._register_task(t)
            finally:
                self.isavaliable = True
            return final_content
        else:
            if not self.becalled or self.becalled[-1][0] != conversationid:
                self.becalled.append([conversationid, message, on_event, group_members])
            else:
                self.becalled[-1][1] = (self.becalled[-1][1] or "") + (message or "")
            return ""

def NewAgent(name, have_skills, have_mcps, init_soul) -> Agent:
    from core.agent.agentmanager import create_agent

    create_agent(name, soul=init_soul, allowed_mcps=have_mcps, allowed_skills=have_skills)
    return Agent(name)
