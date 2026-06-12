"""
多模态调用模块
"""

import asyncio
import json
import os
import time
from functools import partial

import dotenv
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError, HTTPError


dotenv.load_dotenv(override=True)

KEY = os.getenv("APIKEY")
URL = os.getenv("URL")
DEFAULT_MODEL = "deepseek-v4-flash"

# 重试配置
MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("MODEL_RETRY_BACKOFF", "2.0"))  # 指数退避基数（秒）
REQUEST_TIMEOUT = float(os.getenv("MODEL_REQUEST_TIMEOUT", "60"))


# 视为可重试的异常类型
_RETRYABLE_EXCEPTIONS = (Timeout, ConnectionError)
# 视为可重试的 HTTP 状态码
_RETRYABLE_STATUS = (500, 502, 503, 504, 408, 429)


def _make_headers() -> dict:
    return {
        "Authorization": KEY,
        "Content-Type": "application/json",
    }


def _is_retryable_http(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS


def step_model_call(messages: list, tools: list | None = None) -> dict:
    payload = {
        "model": DEFAULT_MODEL,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                URL,
                headers=_make_headers(),
                data=json.dumps(payload),
                timeout=REQUEST_TIMEOUT,
            )

            # 4xx：不重试（请求本身有问题，重试无意义）；5xx/429 等：重试
            if response.status_code >= 400 and not _is_retryable_http(response.status_code):
                response.raise_for_status()  # 让 4xx 走异常分支

            if response.status_code in _RETRYABLE_STATUS:
                raise HTTPError(
                    f"server 返回 {response.status_code}: {response.text[:200]}",
                    response=response,
                )

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

        except _RETRYABLE_EXCEPTIONS as exc:
            last_error = exc
            wait = RETRY_BACKOFF ** attempt  # 2, 4, 8 ...
            print(f"[modelcall] 第 {attempt}/{MAX_RETRIES} 次请求失败（{type(exc).__name__}: {exc}），{wait:.1f}s 后重试")
            if attempt < MAX_RETRIES:
                time.sleep(wait)
            continue
        except HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in _RETRYABLE_STATUS:
                last_error = exc
                wait = RETRY_BACKOFF ** attempt
                print(f"[modelcall] 第 {attempt}/{MAX_RETRIES} 次请求失败（HTTP {status}），{wait:.1f}s 后重试")
                if attempt < MAX_RETRIES:
                    time.sleep(wait)
                continue
            # 4xx 不可重试
            raise
        except ValueError as exc:
            # 响应不是合法 JSON
            last_error = exc
            wait = RETRY_BACKOFF ** attempt
            print(f"[modelcall] 第 {attempt}/{MAX_RETRIES} 次请求返回非 JSON（{exc}），{wait:.1f}s 后重试")
            if attempt < MAX_RETRIES:
                time.sleep(wait)
            continue

    # 重试全部失败
    raise last_error  # type: ignore[misc]


async def step_model_call_async(messages: list, tools: list | None = None) -> dict:
    """在线程池里运行阻塞的 requests 调用，避免阻塞 asyncio 事件循环。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(step_model_call, messages, tools))


def BaseModelCall(text: str = ""):
    messages = [
        {"role": "user", "content": text},
    ]

    try:
        result = step_model_call(messages)
        return result["assistant_message"].get("content")
    except RequestException as e:
        print(f"请求失败: {e}")
