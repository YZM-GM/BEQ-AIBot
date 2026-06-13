import torch
import queue
import os
import sys
import io
import threading
import pyaudio
import wave
import asyncio
import tempfile
import datetime
from pathlib import Path
from core.ModelCall.STTmodelcall import localSTTmodelcall


BASE_DIR = Path(__file__).resolve().parent.parent.parent # 根据实际层级调整
FFMPEG_BIN = BASE_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
os.environ["PATH"] = str(FFMPEG_BIN.parent) + os.pathsep + os.environ["PATH"]

# 录音参数
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
RECORD_SECONDS = 5

# 麦克风资源延迟到第一次 Realtimemonitor() 调用时才初始化
_p: pyaudio.PyAudio | None = None
_stream = None

def process_frames_to_buffer(frames, channels=1, sampwidth=2, framerate=16000):
    """
    将原始 frames 封装为 WAV 格式的二进制流
    """
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth) # 2 表示 16-bit
        wf.setframerate(framerate)
        wf.writeframes(b"".join(frames))

    # 将指针重置到开头，以便 API 读取
    buffer.seek(0)
    buffer.name = "audio.wav"  # 某些 API 需要文件名后缀来推断格式
    return buffer

audio_queue = queue.Queue()

def audio_producer():
    """录音线程：永不停歇地从麦克风读取数据"""
    while True:
        data = _stream.read(CHUNK, exception_on_overflow=False)
        audio_queue.put(data)

def start_stream():
    """打开麦克风并启动后台录音线程；已启动则幂等跳过。"""
    global _p, _stream
    if _stream is not None:
        return
    _p = pyaudio.PyAudio()
    _stream = _p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )
    threading.Thread(target=audio_producer, daemon=True, name="audio-producer").start()

def stop_stream():
    """关闭麦克风、释放 PyAudio 资源。多次调用安全。"""
    global _p, _stream
    if _stream is not None:
        try:
            _stream.stop_stream()
            _stream.close()
        except Exception:
            pass
        _stream = None
    if _p is not None:
        try:
            _p.terminate()
        except Exception:
            pass
        _p = None

async def Realtimemonitor():
    start_stream()
    print("开始录音...")
    buffer = []
    chunk_count = 0
    target_chunks = int(RATE / CHUNK * RECORD_SECONDS)
    # 录音存档目录：<project>/core/ModelCall/audio/
    save_dir = BASE_DIR / "core" / "ModelCall" / "audio"
    save_dir.mkdir(parents=True, exist_ok=True)
    segment_seq = 0
    while True:
        # 非阻塞式从队列取数据
        try:
            data = audio_queue.get_nowait()
            buffer.append(data)
            chunk_count += 1
        except queue.Empty:
            await asyncio.sleep(0.01) # 队列为空则短暂让出 CPU
            continue
        # 当积累到足够时长进行一次识别
        if chunk_count >= target_chunks:
            segment_seq += 1
            audio_buffer = process_frames_to_buffer(buffer)

            # 落盘存档：使用 ISO 时间戳 + 序号命名，方便后续溯源
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = save_dir / f"segment_{ts}_{segment_seq:04d}.wav"
            try:
                with open(save_path, "wb") as f:
                    f.write(audio_buffer.getbuffer())
            except Exception as exc:
                print(f"[audio] 存档失败: {exc}")

            # 重置缓冲区，此时录音线程在后台继续向 queue 填充数据
            buffer = []
            chunk_count = 0

            # 异步调用本地 STT
            import time as _time
            t0 = _time.perf_counter()
            result = await localSTTmodelcall(audio_buffer)
            elapsed_ms = (_time.perf_counter() - t0) * 1000
            print(f"[本地 STT] ⏱ {elapsed_ms:.0f} ms | 结果: {result}")
            if result:
                yield result
