"""
多模态调用模块
"""

import json
import os

import dotenv
import requests


dotenv.load_dotenv(override=True)

KEY = os.getenv("APIKEY")
URL = os.getenv("URL")
DEFAULT_MODEL = "deepseek-v4-flash"


def _make_headers() -> dict:
    return {
        "Authorization": KEY,
        "Content-Type": "application/json",
    }


def step_model_call(messages: list, tools: list | None = None) -> dict:
    payload = {
        "model": DEFAULT_MODEL,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    response = requests.post(
        URL,
        headers=_make_headers(),
        data=json.dumps(payload),
        timeout=60,
    )
    response.raise_for_status()

    res = response.json()
    choices = res.get("choices", [])
    assistant_message = choices[0].get("message", {}) if choices else {}

    return {
        "model": res.get("model", DEFAULT_MODEL),
        "assistant_message": assistant_message,
        "tool_calls": assistant_message.get("tool_calls", []),
        "usage": res.get("usage", {}),
        "finish_reason": choices[0].get("finish_reason") if choices else None,
        "raw": res,
    }


def BaseModelCall(text: str = ""):
    messages = [
        {"role": "user", "content": text},
    ]

    try:
        result = step_model_call(messages)
        return result["assistant_message"].get("content")
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
