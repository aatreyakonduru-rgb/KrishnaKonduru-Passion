"""Test client for the running A2A agent. Uses run_streaming_test from the framework (not client.stream/invoke).

UNVERIFIED against the submodule: the A2AClient construction below follows the guide; confirm against weather_agent/test_client.py.
"""
import asyncio
import sys

import httpx

import config

QUERY = "Which tables does payments-api reference? Cite your sources, or say not found."


async def main(query: str):
    base = f"http://localhost:{config.DEFAULT_PORT}"
    from a2a.client import A2ACardResolver, A2AClient  # type: ignore
    from aicoe_agent_utils.a2a.client_utils import run_streaming_test  # type: ignore
    async with httpx.AsyncClient(timeout=120) as http:
        card = await A2ACardResolver(httpx_client=http, base_url=base).get_agent_card()
        client = A2AClient(httpx_client=http, agent_card=card)
        await run_streaming_test(client, query)


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or QUERY))
