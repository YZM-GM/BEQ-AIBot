"""
主流程
"""

import pathlib
import asyncio

from DashBoard.app import create_app
from core.agent.agent import Agent
from core.agent.agentmanager import ensure_default_agent
from core.mcp.onlinemcp import refresh_all
from core.skills.skillsmanager import registry_skills

BASE_DIR = pathlib.Path(__file__).resolve().parent
BANNER = r"""
    ____  __________
   / __ )/ ____/ __ \
  / __  / __/ / / / /
 / /_/ / /___/ /_/ /
/_____/_____/\___\_\\
"""


def main():
    default_agent = ensure_default_agent()
    tempagent = Agent(default_agent["name"])

    app = create_app(tempagent)
    print("BEQ系统启动中......\n---BotExpertQuest---")
    print(BANNER)
    print("控制面板地址：http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False, threaded=True)


if __name__ == "__main__":
    #asyncio.run(refresh_all())
    #registry_skills()
    main()
