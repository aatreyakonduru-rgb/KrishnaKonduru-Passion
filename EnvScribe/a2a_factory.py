"""Factory: extends A2AAgentFactory. Never calls build_graph().

UNVERIFIED against the submodule (not cloned here): class names/signatures follow the project guide. Check
aicoe-agent-utils/examples/agents_with_mcp/weather_agent/a2a_factory.py and align.
"""
from __future__ import annotations

import config
from envscribe_agent import EnvScribeAgent

try:
    from aicoe_agent_utils.a2a import A2AAgentFactory  # type: ignore
except Exception:  # pragma: no cover
    class A2AAgentFactory:  # minimal stand-in so the module imports without the submodule
        pass


class EnvScribeFactory(A2AAgentFactory):
    def make_agent(self, *args, **kwargs):
        return EnvScribeAgent(*args, **kwargs)

    def make_agent_executor(self, agent, *args, **kwargs):
        # Use the framework's standard executor for the agent (see weather_agent for the exact class).
        from aicoe_agent_utils.a2a import LangGraphAgentExecutor  # type: ignore
        return LangGraphAgentExecutor(agent, *args, **kwargs)

    async def get_mcp_tools(self, *args, **kwargs):
        """Override only if an MCP URL needs special handling. Ensure a trailing slash on each URL (common cause of 'MCP connection failed')."""
        config.MCP_SERVER_URLS[:] = [u if u.endswith("/") else u + "/" for u in config.MCP_SERVER_URLS]
        return await super().get_mcp_tools(*args, **kwargs)
