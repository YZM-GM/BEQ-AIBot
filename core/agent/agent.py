"""
设计agent抽象类的地方，应当抽象成一个具备完整人格的ai智能体
agent抽象类的所有数据：记忆，人格等存储在data文件夹内
存储时以一个完整agent来存储读取
"""

import json
import uuid
from pathlib import Path

from core.agent.agentmanager import ensure_default_agent, get_agent_config
from core.memory.memory import Memory
from core.mcp.MCPs import MCPs
from core.mcp.toolregistry import execute_tool
from core.ModelCall.modelcall import step_model_call
from core.soul.soul import Soul
from core.task.task import Task
from core.skills.skills import Skills

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

        self.config = get_agent_config(name) or ensure_default_agent()
        self.memory = Memory(BASE_PATH, name)
        self.soul = Soul(BASE_PATH, name)
        self.mcps = MCPs(self.config.get("allowed_mcps") or None)
        self.task = Task(BASE_PATH, name)
        self.skill = Skills(BASE_PATH, self.config.get("allowed_skills") or None)

        print(f"初始化Agent--{name}\n")

    def _system_prompt(self) -> str:
        soul_text = self.soul.GetSoul()
        skills_text = self.skill.GetSkills()
        tasks_text = self.task.format_for_prompt()
        return f"\n{soul_text}\n Skills:\n{skills_text}\n当前任务：\n{tasks_text}"

    def _build_messages(self, conversation_id: str | None = None) -> list[dict]:
        return [
            {"role": "system", "content": self._system_prompt()},
            *self.memory.GetMemory(conversation_id=conversation_id, current_agent=self.name),
        ]

    async def chat(self, message: str, on_event=None, max_cycles: int = 150, conversation_id: str | None = None) -> dict:
        turn_id = str(uuid.uuid4())
        tool_trace = []
        usage = {}
        model = ""
        final_content = ""
        conversation_key = conversation_id or "default"
        self.memory.maybe_rollover_session(conversation_key)

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
        self.memory.add_session_memory("user", message, turn_id=turn_id, cycle_index=0, kind="user_message", conversation_id=conversation_key, speaker="user", source_agent="user")

        for cycle_index in range(1, max_cycles + 1):
            emit("cycle_start", cycle_index, f"开始第 {cycle_index} 轮思考")
            messages = self._build_messages(conversation_id=conversation_key)

            step = step_model_call(messages, self.mcps.toollist)
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

            if self.task.GetOpenTasks():
                hascomplete = self.task.check_complete(messages)
                if hascomplete:
                    break
            else:
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


def NewAgent(name, have_skills, have_mcps, init_soul) -> Agent:
    from core.agent.agentmanager import create_agent

    create_agent(name, soul=init_soul, allowed_mcps=have_mcps, allowed_skills=have_skills)
    return Agent(name)
