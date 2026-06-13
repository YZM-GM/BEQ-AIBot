import requests
import json
import os
import time
import dotenv
import io

url = "https://www.dmxapi.cn/v1/responses"
api_key = os.getenv("APIKEY")

def TTSmodelcall(text:str) -> io.BytesIO:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"{api_key}", 
    }

    payload = {
        "model": "speech-2.8-hd",

        # 【input】(string, 必填) 需要合成语音的文本，长度限制小于 10000 字符，若文本长度大于 3000 字符，推荐使用流式输出
        # 段落切换用换行符标记
        # 停顿控制：支持自定义文本之间的语音时间间隔，以实现自定义文本语音停顿时间的效果。使用方式：在文本中增加<#x#>标记，x 为停顿时长（单位：秒），范围 [0.01, 99.99]，最多保留两位小数。
        #   文本间隔时间需设置在两个可以语音发音的文本之间，不可连续使用多个停顿标记
        # 语气词标签：支持在文本中插入语气词标签。支持的语气词：
        #   (laughs)（笑声）、(chuckle)（轻笑）、(coughs)（咳嗽）、(clear-throat)（清嗓子）、
        #   (groans)（呻吟）、(breath)（正常换气）、(pant)（喘气）、(inhale)（吸气）、(exhale)（呼气）、(gasps)（倒吸气）、(sniffs)（吸鼻子）、
        #   (sighs)（叹气）、(snorts)（喷鼻息）、(burps)（打嗝）、(lip-smacking)（咂嘴）、(humming)（哼唱）、(hissing)（嘶嘶声）、(emm)（嗯）、(sneezes)（喷嚏）
        "input": "欢迎使用DMXAPI，开始语音合成。",

        "stream": False,# 控制是否流式输出。默认 false，即不开启流式
        "stream_options": {
                # 设置最后一个 chunk 是否包含拼接后的语音 hex 数据。默认值为 False，即最后一个 chunk 中包含拼接后的完整hex 数据
                  "exclude_aggregated_audio": False
        },
        "voice_setting": {
            # 【voice_id】(string, 必填) 音色 ID
            # 合成音频的音色编号。若需要设置混合音色，请设置 timbre_weights 参数，本参数设置为空值。
            # 支持系统音色、复刻音色以及文生音色三种类型
            # 可查看 系统音色列表 或使用 查询可用音色 API 查询系统支持的全部音色，详见下方链接
            # 系统音色列表: https://platform.minimaxi.com/docs/faq/system-voice-id
            # 查询可用音色 API: https://platform.minimaxi.com/docs/api-reference/voice-management-get
            "voice_id": "h20260212",

            "speed": 1,# 合成音频的语速，取值越大，语速越快。取值范围 [0.5,2]，默认值为1.0

            "vol": 1,# 合成音频的音量，取值越大，音量越高。取值范围 (0,10]，默认值为 1.0

            "pitch": 0,# 合成音频的语调，取值范围 [-12,12]，默认值为 0，其中 0 为原音色输出

            # 【emotion】(string, 可选) 控制合成语音的情绪
            # 可选值: "happy"(高兴) / "sad"(悲伤) / "angry"(愤怒) / "fearful"(害怕) /
            #         "disgusted"(厌恶) / "surprised"(惊讶) / "calm"(平静) /
            #         "fluent"(生动) / "whisper"(耳语)
            # 模型会根据输入文本自动匹配合适的情绪，一般无需手动指定
            "emotion": "fluent",

            "text_normalization":  False, # 是否启用中文、英语文本规范化，开启后可提升数字阅读场景的性能，但会略微增加延迟，默认值为 false
            # 【latex_read】 控制是否朗读 latex 公式，默认为 false
            #   仅支持中文，开启该参数后，language_boost 参数会被设置为 Chinese
            #   请求中的公式需要在公式的首尾加上 $$
            #   请求中公式若有 "\"，需转义成 "\\".
            "latex_read": False
        },
        "audio_setting": {
            "sample_rate": 32000,# 生成音频的采样率。可选范围[8000，16000，22050，24000，32000，44100]，默认为 32000
            "bitrate": 128000,# 生成音频的比特率。可选范围[32000，64000，128000，256000]，默认值为 128000。该参数仅对 mp3 格式的音频生效
            "format": "mp3", # 生成音频的格式，wav 仅在非流式输出下支持。 可用选项:mp3,pcm,flac,wav
            "channel": 1,# 生成音频的声道数。可选范围：[1,2]，其中 1 为单声道，2 为双声道，默认值为 1

            # 【force_cbr】对于音频恒定比特率（cbr）控制，可选 false、 true。当此参数设置为 true，将以恒定比特率方式进行音频编码。
            # 注意：本参数仅当音频设置为流式输出，且音频格式为 mp3 时生效。
            "force_cbr": False
        },
        "pronunciation_dict": {
            # 【tone】定义需要特殊标注的文字或符号对应的注音或发音替换规则
            # 在中文文本中，声调用数字表示：
            #  一声为 1，二声为 2，三声为 3，四声为 4，轻声为 5
            # 示例: ["燕少飞/(yan4)(shao3)(fei1)", "omg/oh my god"]
            "tone": [
                "处理/(chu3)(li3)",
                "危险/dangerous"
            ]
        },
        "timber_weights":[{
            #【voice_id】合成音频的音色编号，须和weight参数同步填写。
            # 支持系统音色、复刻音色以及文生音色三种类型。
            # 系统支持的全部音色可查看 系统音色列表，也可使用 查询可用音色 API 查询系统支持的全部音色
            #  系统音色列表: https://platform.minimaxi.com/docs/faq/system-voice-id
            #  查询可用音色 API: https://platform.minimaxi.com/docs/api-reference/voice-management-get
            "voice_id":"Jonathan04",

            # 【weight】合成音频各音色所占的权重，须与 voice_id 同步填写
            # 可选值范围为[1, 100]，最多支持 4 种音色混合，单一音色取值占比越高，合成音色与该音色相似度越高.
            "weight":10
        }],
        # 【language_boost】 是否增强对指定的小语种和方言的识别能力。默认值为 null，可设置为 auto 让模型自主判断。
        # 支持的语言:
        #   Chinese, Chinese,Yue, English, Arabic, Russian, Spanish, French, Portuguese,
        #   German, Turkish, Dutch, Ukrainian, Vietnamese, Indonesian, Japanese, Italian,
        #   Korean, Thai, Polish, Romanian, Greek, Czech, Finnish, Hindi, Bulgarian,
        #   Danish, Hebrew, Malay, Persian, Slovak, Swedish, Croatian, Filipino, Hungarian,
        #   Norwegian, Slovenian, Catalan, Nynorsk, Tamil, Afrikaans, auto
        "language_boost":"auto",

        # 【subtitle_enable】控制是否开启字幕服务，默认值为 false
        # 此参数仅在非流式输出场景下有效
        "subtitle_enable": False,

        # 【voice_modify】声音效果器设置，该参数支持的音频格式：非流式：mp3, wav, flac；流式：mp3
        "voice_modify":{
            "pitch": 0,# 音高调整（低沉/明亮），范围 [-100,100]，数值接近 -100，声音更低沉；接近 100，声音更明亮。必填范围: -100 <= x <= 100
            "intensity" : 0,# 强度调整（力量感/柔和），范围 [-100,100]，数值接近 -100，声音更刚劲；接近 100，声音更轻柔。必填范围: -100 <= x <= 100
            "timbre": 0,# 音色调整（磁性/清脆），范围 [-100,100]，数值接近 -100，声音更浑厚；数值接近 100，声音更清脆。必填范围: -100 <= x <= 100

            # 【sound_effects】音效设置，单次仅能选择一种
            # 可选值: "spacious_echo（空旷回音 / auditorium_echo（礼堂广播） / lofi_telephone（电话失真） /robotic（电音）
            "sound_effects": "spacious_echo"
        },
        "subtitle_enable":False,  # 重复字段，同上
        # 【output_format】控制输出结果形式的参数，可选值范围为[url, hex]，默认值为 hex
        # 该参数仅在非流式场景生效，流式场景仅支持返回 hex 形式。返回的 url 有效期为 24 小时
        "output_format":"hex",
        "aigc_watermark":False,# 控制在合成音频的末尾添加音频节奏标识，默认值为 False。该参数仅对非流式合成生效
    }


    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        result = response.json()
        print("请求成功！")
        import copy
        result_preview = copy.deepcopy(result)
        if "data" in result_preview and "audio" in result_preview["data"]:
            result_preview["data"]["audio"] = f"[hex数据, 长度: {len(result['data']['audio'])} 字符]"
        print("原始JSON返回内容:", result_preview)

        # 如果返回了音频数据，保存为文件
        if "data" in result and "audio" in result["data"]:
            audio_data = result["data"]["audio"]
            audio_bytes = bytes.fromhex(audio_data)
            audio_buffer = io.BytesIO(audio_bytes)
            return audio_buffer

        else:
            print("响应内容:", result)
    else:
        print(f"请求失败，状态码: {response.status_code}")
        print("错误信息:", response.text)