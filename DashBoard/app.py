import json
import queue
import threading
import uuid

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from core.agent.agent import Agent
from core.agent.agentmanager import (
    create_agent,
    delete_agent,
    get_agent_config,
    list_agents,
    update_agent_config,
)
from core.chat.chatmanager import (
    create_conversation,
    ensure_single_conversation,
    get_conversation,
    list_conversations,
    update_conversation,
)
from core.chat.groupchat import GroupChatRunner, SCHEDULER
from core.mcp.mcpmanager import add_online_server, list_all_mcps, refresh_all_online_servers, set_online_server_enabled
from core.skills.skillsmanager import get_skill_detail, list_skills, rescan_skills, set_skill_enabled
from core.soul.soulmanager import create_soul, delete_soul, get_soul, list_souls, update_soul


def create_app(agent):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    turns = {}

    def _json_body():
        return request.get_json(silent=True) or {}

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/chat", methods=["POST"])
    def create_turn():
        data = _json_body()
        message = data.get("message", "").strip()
        agent_name = data.get("agent_name") or agent.name
        if not message:
            return jsonify({"error": "消息不能为空"}), 400
        if get_agent_config(agent_name) is None:
            return jsonify({"error": f"agent 不存在: {agent_name}"}), 404

        conversation = ensure_single_conversation(agent_name)
        turn_id = str(uuid.uuid4())
        turns[turn_id] = {
            "message": message,
            "agent_name": agent_name,
            "conversation_id": conversation["id"],
            "conversation_type": "single",
        }
        update_conversation(conversation["id"], last_message_preview=message[:100])
        return jsonify({"turn_id": turn_id, "conversation_id": conversation["id"]})

    @app.route("/api/chat/stream/<turn_id>")
    def stream_turn(turn_id):
        turn = turns.get(turn_id)
        if turn is None:
            return jsonify({"error": "turn_id 不存在"}), 404

        q = queue.Queue()
        done = object()

        def on_event(event):
            if not event.get("turn_id"):
                event["turn_id"] = turn_id
            q.put(event)

        def worker():
            try:
                import asyncio
                chat_agent = Agent(turn["agent_name"])
                asyncio.run(chat_agent.chat(turn["message"], on_event=on_event, conversation_id=turn.get("conversation_id")))
            except Exception as exc:
                q.put(
                    {
                        "turn_id": turn_id,
                        "type": "error",
                        "message": f"agent 运行失败: {exc}",
                        "data": {},
                    }
                )
            finally:
                q.put(done)
                turns.pop(turn_id, None)

        threading.Thread(target=worker, daemon=True).start()

        @stream_with_context
        def generate():
            while True:
                item = q.get()
                if item is done:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    @app.route("/api/conversations", methods=["GET", "POST"])
    def conversations_api():
        if request.method == "GET":
            return jsonify({"items": list_conversations(), "scheduler": SCHEDULER.snapshot()})
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
        if not message:
            return jsonify({"error": "消息不能为空"}), 400
        turn_id = str(uuid.uuid4())
        turns[turn_id] = {
            "message": message,
            "agent_name": conversation.get("owner_agent") or agent.name,
            "conversation_id": conversation_id,
            "conversation_type": conversation.get("type", "single"),
        }
        update_conversation(conversation_id, last_message_preview=message[:100])
        return jsonify({"turn_id": turn_id, "conversation_id": conversation_id})

    @app.route("/api/conversations/<conversation_id>/stream/<turn_id>")
    def conversation_stream(conversation_id, turn_id):
        turn = turns.get(turn_id)
        if turn is None or turn.get("conversation_id") != conversation_id:
            return jsonify({"error": "turn_id 不存在"}), 404
        conversation = get_conversation(conversation_id)
        if conversation is None:
            return jsonify({"error": f"conversation 不存在: {conversation_id}"}), 404

        q = queue.Queue()
        done = object()

        def on_event(event):
            payload = dict(event)
            payload.setdefault("turn_id", turn_id)
            payload.setdefault("conversation_id", conversation_id)
            q.put(payload)

        def worker():
            try:
                import asyncio
                if conversation.get("type") == "group":
                    runner = GroupChatRunner(conversation_id)
                    asyncio.run(runner.run(turn["message"], on_event=on_event))
                else:
                    chat_agent = Agent(turn["agent_name"])
                    asyncio.run(chat_agent.chat(turn["message"], on_event=on_event, conversation_id=conversation_id))
            except Exception as exc:
                q.put(
                    {
                        "turn_id": turn_id,
                        "conversation_id": conversation_id,
                        "type": "error",
                        "message": f"conversation 运行失败: {exc}",
                        "data": {},
                    }
                )
            finally:
                q.put(done)
                turns.pop(turn_id, None)

        threading.Thread(target=worker, daemon=True).start()

        @stream_with_context
        def generate():
            while True:
                item = q.get()
                if item is done:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    @app.route("/api/manage/agents", methods=["GET", "POST"])
    def manage_agents():
        if request.method == "GET":
            return jsonify({"items": list_agents()})
        data = _json_body()
        try:
            item = create_agent(
                name=data.get("name", ""),
                soul=data.get("soul", "default"),
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
                item = update_agent_config(name, _json_body())
                return jsonify(item)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        try:
            delete_agent(name)
            return jsonify({"ok": True})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/mcps", methods=["GET"])
    def manage_mcps():
        return jsonify(list_all_mcps())

    @app.route("/api/manage/mcps/online", methods=["POST"])
    def add_online_mcp():
        try:
            item = add_online_server(_json_body().get("url", ""))
            return jsonify(item), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/manage/mcps/online/refresh", methods=["POST"])
    def refresh_online_mcp():
        return jsonify({"items": refresh_all_online_servers()})

    @app.route("/api/manage/mcps/online/toggle", methods=["PUT"])
    def toggle_online_mcp():
        data = _json_body()
        try:
            item = set_online_server_enabled(data.get("url", ""), data.get("enabled", True))
            return jsonify(item)
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
            item = create_soul(data.get("name", ""), data.get("content", ""))
            return jsonify(item), 201
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
