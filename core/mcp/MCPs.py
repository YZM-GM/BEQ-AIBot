"""
MCP模块
"""

import core.mcp.toolregistry as tr


class MCPs:
    def __init__(self, allow_mcps=None):
        self.toollist = tr.get_all_tools_spec(allow_mcps=allow_mcps)

    def create_mcp(self, allow_mcps=None):
        if allow_mcps is None:
            self.toollist = tr.get_all_tools_spec()
            return
        allow_set = set(allow_mcps)
        self.toollist = [
            tool for tool in tr.get_all_tools_spec()
            if tool["function"]["name"] in allow_set
        ]
