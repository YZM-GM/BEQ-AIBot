"""
本地MCP工具合集
整理完成的工具信息存储在同目录下的localmcpdata.json
"""

import os
import json
import subprocess
import shlex
from pathlib import Path
from typing import Any
import requests
import platform
from mcp.server.fastmcp import FastMCP
from core.skills.skillsmanager import get_skillmd
from core.task.task import Task

mcp = FastMCP("MyToolsServer")

_DATA_FILE = os.path.join(os.path.dirname(__file__), "localmcpdata.json")


@mcp.tool(description="列出指定目录的文件树结构")
async def list_directory(agent: Any, path: str) -> str:
    if not os.path.exists(path):
        return f"错误: 路径 '{path}' 不存在。"
    if not os.path.isdir(path):
        return f"错误: '{path}' 不是一个目录。"

    structure = []
    for root, dirs, files in os.walk(path):
        level = root.replace(path, "").count(os.sep)
        indent = "  " * level
        structure.append(f"{indent}{os.path.basename(root)}/")
        sub_indent = "  " * (level + 1)
        for fname in files:
            structure.append(f"{sub_indent}{fname}")

    return "\n".join(structure)


@mcp.tool(description="在指定位置生成txt文件")
async def create_text_file(agent: Any, full_path: str, content: str) -> str:
    try:
        print(full_path)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"成功: 文件已创建于 {full_path}"
    except Exception as e:
        return f"错误: 无法生成文件，原因: {str(e)}"


@mcp.tool(description="读取指定位置文件")
async def read_file(agent: Any, full_path: str) -> str:
    if Path(full_path).exists():
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f"文件内容：{f.read()}"
        except Exception as e:
            return f"错误: 无法读取文件，原因: {str(e)}"
    else:
        return f"错误: 文件 '{full_path}' 不存在。"


@mcp.tool()
async def run_bash_command(agent: Any, command: str) -> str:
    os_name = platform.system()
    
    forbidden_keywords = ['rm -rf', 'del /f /s /q', 'format']
    if any(keyword in command for keyword in forbidden_keywords):
        return "❌ 错误：该命令包含高危操作，被系统安全策略拦截。"
    try:
        result = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=15,
            encoding='utf-8', 
            errors='replace'
        )
        if result.returncode == 0:
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            
            if not stdout and not stderr:
                return "✅ 执行成功，但没有产生任何控制台输出 (stdout/stderr 为空)。可能命令格式错误或无法识别。"
            
            response = "✅ 执行成功:\n"
            if stdout:
                response += f"[Standard Output]\n{stdout}\n"
            if stderr:
                response += f"[Standard Error (Warnings)]\n{stderr}\n"
            return response
            
        else:
            return (f"执行失败 (退出状态码 {result.returncode}):\n"
                    f"[Standard Error]\n{result.stderr.strip()}\n"
                    f"[Standard Output]\n{result.stdout.strip()}")
    except subprocess.TimeoutExpired:
        return "错误：命令执行超时15秒。如果执行的是网络请求或耗时任务，请考虑优化脚本或分步执行。"
    except Exception as e:
        return f"执行异常: {str(e)}"


@mcp.tool()
async def task_generate(agent: Any, tasks: list[str]) -> str:
    agent.task.apply_tasks(tasks)
    return f"成功生成 {tasks} 任务。"

@mcp.tool()
async def get_skill(agent: Any, skill_name: str) -> str:
    path,skillmd = get_skillmd(skill_name)
    if path == None:
        return f"技能名字{skill_name}错误"

    return f"skill文件路径:{path}。技能.md文件内容：{skillmd}"

@mcp.tool()
async def request_url(agent: Any, url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return f"请求处理失败: {str(e)}"
    return json.dumps(response.json(), indent=2, ensure_ascii=False)

if __name__ == "__main__":
    mcp.run()
