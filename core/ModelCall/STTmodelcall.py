import requests
import os
import json
import dotenv
import io
import whisper
import asyncio
import torch
print(f"CUDA 是否可用: {torch.cuda.is_available()}")
print(f"当前设备名称: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else '无'}")
api_key = os.getenv("APIKEY")
url = "https://www.dmxapi.cn/v1/audio/transcriptions"

model = whisper.load_model("small",device="cuda")

async def STTmodelcall(audio:io.BytesIO):
    import time
    headers = {
        "Authorization": api_key
    }

    # 【音频文件配置】
    # 待转写的音频文件路径(支持 flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm)


    audio.name = "audio.mp3"

    files = {
        "file": audio,              # 音频文件二进制流
        "model": (None, "whisper-1"),    # 指定使用 Whisper-1 模型
    }

    # 发送 POST 请求到音频转写 API
    t0 = time.perf_counter()
    response = requests.post(url, headers=headers, files=files)
    elapsed_ms = (time.perf_counter() - t0) * 1000


    print(f"📊 HTTP 状态码: {response.status_code}  ⏱  耗时 {elapsed_ms:.0f} ms")
    print("=" * 60)
    print("📄 响应内容:")
    print("=" * 60)

    if response.status_code == 200:
        try:
            # 解析 JSON 响应数据
            response_data = response.json()
            # 格式化输出,保留中文字符,缩进 2 个空格
            return (json.dumps(response_data, ensure_ascii=False, indent=2))
        except requests.exceptions.JSONDecodeError:
            # 如果响应不是有效的 JSON 格式,输出原始文本
            print("⚠️ 响应不是 JSON 格式:")
            print(response.text)
    else:
        try:
            error_data = response.json()
            print("❌ 错误详情:")
            print(json.dumps(error_data, ensure_ascii=False, indent=2))
        except:
            print("❌ 请求失败,原始响应:")
            print(response.text)

async def localSTTmodelcall(audio: io.BytesIO) -> str:
    import tempfile, os
    audio.seek(0)
    data = audio.read()

    def _transcribe():
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(data)
            tmp_path = f.name
        try:
            return model.transcribe(tmp_path, language="zh")
        finally:
            os.unlink(tmp_path)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _transcribe)
    return result["text"]