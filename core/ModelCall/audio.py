import torch


import whisper

import os
import sys

import pyaudio
import wave
import tempfile
from pathlib import Path

device = "cuda" if torch.cuda.is_available() else "cpu"
print(device)
model = whisper.load_model("small", device=device)

BASE_DIR = Path(__file__).resolve().parent.parent.parent # 根据实际层级调整
FFMPEG_BIN = BASE_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
os.environ["PATH"] = str(FFMPEG_BIN.parent) + os.pathsep + os.environ["PATH"]

# 录音参数
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
RECORD_SECONDS = 5

p = pyaudio.PyAudio()

stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)



print("开始录音...")

while True:
    frames = []
    for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)
    
    # 保存临时文件
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
        wf = wave.open(temp_audio.name, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        # 转录
        result = model.transcribe(temp_audio.name, language="zh")
        print(f"识别结果: {result['text']}")