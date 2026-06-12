"""
主流程
"""

import pathlib
import asyncio
from DashBoard.app import create_app
from core.agent.agentmanager import ensure_default_agent, AGENT_MANAGER

from core.mcp.onlinemcp import refresh_all

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


def main():
    ensure_default_agent()
    AGENT_MANAGER

    app = create_app()
    print("BEQ系统启动中......\n---BotExpertQuest---")
    display_banner()
    print("控制面板地址：http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False, threaded=True)


if __name__ == "__main__":
    asyncio.run(refresh_all())
    print(f"终端是否支持颜色: {console.color_system}")
    #registry_skills()
    main()