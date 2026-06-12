import json
import queue
import threading
import uuid

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
import logging

logging.getLogger('werkzeug').setLevel(logging.ERROR)
for _n in ["httpx", "httpcore", "urllib3", "openai", "requests"]:
    logging.getLogger(_n).setLevel(logging.WARNING)

from core.agent.agentmanager import AGENT_MANAGER
from core.agent.agentmanager import (
    create_agent, delete_agent, get_agent_config, list_agents, update_agent_config,
)
from core.chat.chatmanager import (
    create_conversation, ensure_single_conversation,
    get_conversation, list_conversations, update_conversation,
)
from core.chat.groupchat import GroupChatRunner
from core.chat.history import load_history, append_record
from core.mcp.mcpmanager import (
    add_online_server, list_all_mcps, refresh_all_online_servers,
    set_online_server_enabled, set_local_tool_enabled,
)
from core.skills.skillsmanager import get_skill_detail, list_skills, rescan_skills, set_skill_enabled
from core.soul.soulmanager import create_soul, delete_soul, get_soul, list_souls, update_soul


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.logger.setLevel(logging.ERROR)

    # ── 全局持久 SSE 队列 ───────────────────────────────────────────
    _STOP_SSE = object()
    _global_queue: queue.Queue = queue.Queue()

    def push_event(event: dict) -> None:
        _global_queue.put(event)

    def _json_body():
        return request.get_json(silent=True) or {}

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── 全局持久 SSE 流 ─────────────────────────────────────────────
    @app.route("/api/stream")
    def global_stream():
        @stream_with_context
        def generate():
            # 重连时清空积压旧事件（单用户系统，旧 UI 已丢失无意义）
            while not _global_queue.empty():
                try:
                    _global_queue.get_nowait()
                except queue.Empty:
                    break
            yield ": connected\n\n"
            while True:
                try:
                    item = _global_queue.get(timeout=20)
                except queue.Empty:
                    yield ": keepalive\n\n"   # SSE 注释行，穿透反向代理不触发 onmessage
                    continue
                if item is _STOP_SSE:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    # ── 显示历史 ────────────────────────────────────────────────────
    @app.route("/api/conversations/<conversation_id>/history", methods=["GET"])
    def conversation_history(conversation_id):
        return jsonify({"records": load_history(conversation_id)})

    # ── 旧 /api/chat 单聊（保留兼容）───────────────────────────────
    @app.route("/api/chat", methods=["POST"])
    def create_turn():
        data = _json_body()
        message = data.get("message", "").strip()
        agent_name = data.get("agent_name") or ""
        if not message:
            return jsonify({"error": "消息不能为空"}), 400
        if not agent_name or get_agent_config(agent_name) is None:
            return jsonify({"error": f"agent 不存在: {agent_name}"}), 404

        conversation = ensure_single_conversation(agent_name)
        turn_id = str(uuid.uuid4())
        update_conversation(conversation["id"], last_message_preview=message[:100])
        return jsonify({"turn_id": turn_id, "conversation_id": conversation["id"]})

    # ── conversation 系统（群聊+单聊统一入口）─────────────────────
    @app.route("/api/conversations", methods=["GET", "POST"])
    def conversations_api():
        if request.method == "GET":
            return jsonify({"items": list_conversations()})
        data = _json_body()
        conversation_type = data.get("type", "single")
        owner_agent = data.get("owner_agent", "")
        member_agents = data.get("member_agents") or []
        if conversation_type == "group":
            if not owner_agent:
                return jsonify({"error": "群聊必须指定群主"}), 400
            if get_agent_config(owner_agent) is None:
                return jsonify({"error": f"群主不存在: {owner_agent}"}), 404
        try:
            item = create_conversation(data.get("title", ""), conversation_type, owner_agent, member_agents)
            return jsonify(item), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/conversations/<conversation_id>", methods=["GET"])
    def conversation_detail(conversation_id):
        item = get_conversation(conversation_id)
        if item is None:
            return jsonify({"error": f"conversation 不存在: {conversation_id}"}), 404
        return jsonify(item)

    @app.route("/api/conversations/<conversation_id>/turns", methods=["POST"])
    def conversation_turn(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            return jsonify({"error": f"conversation 不存在: {conversation_id}"}), 404
        data = _json_body()
        message = data.get("message", "").strip()
        team_mode = bool(data.get("team_mode", False))
        if not message:
            return jsonify({"error": "消息不能为空"}), 400

        append_record(conversation_id, {"role": "user", "content": message})
        turn_id = str(uuid.uuid4())
        update_conversation(conversation_id, last_message_preview=message[:100])

        def on_event(event):
            payload = dict(event)
            payload.setdefault("turn_id", turn_id)
            payload.setdefault("conversation_id", conversation_id)
            if payload.get("type") == "final_answer":
                d = payload.get("data", {})
                content = d.get("content", "")
                if content:
                    append_record(conversation_id, {
                        "role": "agent",
                        "agent_name": d.get("agent_name", ""),
                        "turn_key": d.get("turn_key", ""),
                        "content": content,
                    })
            push_event(payload)

        def worker():
            try:
                import asyncio
                is_group = conversation.get("type") == "group"
                owner = conversation.get("owner_agent", "")
                # 所有模式都传完整成员列表，确保用户消息中的 @mention 能被识别
                all_members = list(conversation.get("member_agents") or [owner])
                if not all_members:
                    all_members = [owner]

                if is_group and team_mode:
                    runner = GroupChatRunner(conversation_id)
                    asyncio.run(runner.run(message, on_event=on_event, team_mode=True))
                else:
                    # 普通模式（含单聊、群聊非团队）：直接发给 owner，但传完整成员列表
                    # 这样用户消息里的 @member 能被 _extract_mentions 识别并触发级联
                    asyncio.run(AGENT_MANAGER.run_group_chat(
                        owner, conversation_id, message, all_members, on_event,
                    ))
            except Exception as exc:
                push_event({
                    "turn_id": turn_id, "conversation_id": conversation_id,
                    "type": "error", "message": f"运行失败: {exc}", "data": {},
                })
            finally:
                push_event({
                    "type": "turn_complete",
                    "turn_id": turn_id,
                    "conversation_id": conversation_id,
                    "data": {},
                })

        threading.Thread(target=worker, daemon=True).start()
        return jsonify({"turn_id": turn_id, "conversation_id": conversation_id})

    # ── 管理接口 ───────────────────────────────────────────────────
    @app.route("/api/manage/agents", methods=["GET", "POST"])
    def manage_agents():
        if request.method == "GET":
            return jsonify({"items": list_agents()})
        data = _json_body()
        try:
            item = create_agent(
                name=data.get("name", ""), soul=data.get("soul", "default"),
                allowed_mcps=data.get("allowed_mcps") or [],
                allowed_skills=data.get("allowed_skills") or [],
                enabled=data.get("enabled", True),
            )
            return jsonify(item), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/agents/<name>", methods=["GET", "PUT", "DELETE"])
    def manage_agent(name):
        if request.method == "GET":
            item = get_agent_config(name)
            if item is None:
                return jsonify({"error": f"agent 不存在: {name}"}), 404
            return jsonify(item)
        if request.method == "PUT":
            try:
                return jsonify(update_agent_config(name, _json_body()))
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        try:
            delete_agent(name)
            return jsonify({"ok": True})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/agents/<name>/soul", methods=["GET", "PUT"])
    def manage_agent_soul(name):
        from pathlib import Path as _Path
        import json as _json
        soul_path = _Path(__file__).resolve().parent.parent / "core" / "agent" / name / "soul" / "soul.json"
        if request.method == "GET":
            if not soul_path.exists():
                return jsonify({"error": f"agent soul 不存在: {name}"}), 404
            with open(soul_path, "r", encoding="utf-8") as f:
                content = _json.load(f)
            return jsonify({"name": name, "content": content})
        data = _json_body()
        content = data.get("content", "")
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        with open(soul_path, "w", encoding="utf-8") as f:
            _json.dump(content, f, ensure_ascii=False, indent=2)
        return jsonify({"name": name, "content": content})

    @app.route("/api/manage/mcps", methods=["GET"])
    def manage_mcps():
        return jsonify(list_all_mcps())

    @app.route("/api/manage/mcps/online", methods=["POST"])
    def add_online_mcp():
        try:
            return jsonify(add_online_server(_json_body().get("url", ""))), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/mcps/online/refresh", methods=["POST"])
    def refresh_online_mcp():
        return jsonify({"items": refresh_all_online_servers()})

    @app.route("/api/manage/mcps/online/toggle", methods=["PUT"])
    def toggle_online_mcp():
        data = _json_body()
        try:
            return jsonify(set_online_server_enabled(data.get("url", ""), data.get("enabled", True)))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/mcps/local/toggle", methods=["PUT"])
    def toggle_local_mcp():
        data = _json_body()
        try:
            return jsonify(set_local_tool_enabled(data.get("name", ""), data.get("enabled", True)))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/skills", methods=["GET"])
    def manage_skills():
        return jsonify({"items": list_skills()})

    @app.route("/api/manage/skills/rescan", methods=["POST"])
    def manage_skills_rescan():
        return jsonify({"items": rescan_skills()})

    @app.route("/api/manage/skills/<name>", methods=["GET", "PUT"])
    def manage_skill(name):
        if request.method == "GET":
            try:
                return jsonify(get_skill_detail(name))
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 404
        data = _json_body()
        try:
            return jsonify(set_skill_enabled(name, data.get("enabled", True)))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/souls", methods=["GET", "POST"])
    def manage_souls():
        if request.method == "GET":
            return jsonify({"items": list_souls()})
        data = _json_body()
        try:
            return jsonify(create_soul(data.get("name", ""), data.get("content", ""))), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/souls/<name>", methods=["GET", "PUT", "DELETE"])
    def manage_soul(name):
        if request.method == "GET":
            try:
                return jsonify({"name": name, "content": get_soul(name)})
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 404
        if request.method == "PUT":
            try:
                return jsonify(update_soul(name, _json_body().get("content", "")))
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        try:
            delete_soul(name)
            return jsonify({"ok": True})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return app
