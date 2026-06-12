"""前端显示用的对话历史，与 agent 记忆无关"""
import json
from datetime import datetime
from pathlib import Path

HISTORY_DIR = Path(__file__).resolve().parent / "conversation_history"


def _file(conv_id: str) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{conv_id}.json"


def load_history(conv_id: str) -> list[dict]:
    f = _file(conv_id)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_record(conv_id: str, record: dict) -> None:
    records = load_history(conv_id)
    record.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    records.append(record)
    _file(conv_id).write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
