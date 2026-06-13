"""
主流程
"""

import pathlib
import asyncio
import threading
import datetime
from DashBoard.app import create_app
from core.agent.agentmanager import ensure_default_agent, AGENT_MANAGER
from core.mcp.onlinemcp import refresh_all
import core.ModelCall.audio as au

from rich.console import Console
from rich.text import Text
console = Console(force_terminal=True, color_system="truecolor")
BASE_DIR = pathlib.Path(__file__).resolve().parent

def display_banner():
    BANNER = r"""
    ____  __________      ____        __
   / __ )/ ____/ __ \    / __ )____  / /_
  / __  / __/ / / / /   / __  / __ \/ __/
 / /_/ / /___/ /_/ /   / /_/ / /_/ / /_
/_____/_____/\___\_\  /_____/\____/\__/

"""
    console.print(BANNER, style="#ff00ff")

async def keeping_alive():
    print("录音线程已启动，正在监听...")

    try:
        # 使用 async for 持续接收生成器产出的结果
        async for result in au.Realtimemonitor():
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 识别结果: {result}")

    except KeyboardInterrupt:
        print("停止监控...")
    finally:
        # 在此处执行清理操作
        au.stop_stream()

def run_flask():
    """在独立线程中启动 Flask，避免阻塞 asyncio 事件循环。"""
    app = create_app()
    # debug=False：避免 reloader 副作用与手动线程化冲突
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)

async def main():

    ensure_default_agent()
    AGENT_MANAGER

    print("BEQ系统启动中......\n---BotExpertQuest---")
    display_banner()
    print("控制面板地址：http://127.0.0.1:5000")

    flask_thread = threading.Thread(target=run_flask, daemon=True, name="flask")
    flask_thread.start()
    # 把整个事件循环让给音频监听；Flask 在独立线程里服务
    await keeping_alive()




if __name__ == "__main__":
    #asyncio.run(refresh_all())
    #print(f"终端是否支持颜色: {console.color_system}")
    #registry_skills()

    asyncio.run(main())