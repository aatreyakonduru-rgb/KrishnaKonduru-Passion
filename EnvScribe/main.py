"""Server entry point. NEVER name this file __main__.py.

Starts the web UI (control API) in a background thread and the A2A server via aicoe_agent_utils.utils.start_a2a_server.
UNVERIFIED: the start_a2a_server parameters follow the guide; confirm against the weather_agent main.py.
"""
import threading

import asyncclick as click
import uvicorn

import config
from a2a_factory import EnvScribeFactory


def _start_ui():
    from scribe.ui.app import create_app
    uvicorn.run(create_app(config.TARGETS_FILE), host=config.UI_HOST, port=config.UI_PORT, log_level="warning")


@click.command()
@click.option("--host", default=config.DEFAULT_HOST)
@click.option("--port", default=config.DEFAULT_PORT, type=int)
@click.option("--ui/--no-ui", default=True, help="Serve the EnvScribe web UI alongside the A2A server")
@click.option("--ui-only", is_flag=True, help="Serve only the web UI (no LLM or A2A required)")
async def main(host, port, ui, ui_only):
    if ui_only:
        from scribe.ui.app import create_app
        await uvicorn.Server(uvicorn.Config(create_app(config.TARGETS_FILE), host=config.UI_HOST,
                                            port=config.UI_PORT, log_level="warning")).serve()
        return
    problems = config.validate()
    if problems:
        raise click.ClickException("; ".join(problems))
    if ui:
        threading.Thread(target=_start_ui, name="envscribe-ui", daemon=True).start()
    from aicoe_agent_utils.utils import start_a2a_server  # type: ignore
    factory = EnvScribeFactory()
    agent = factory.make_agent()
    executor = factory.make_agent_executor(agent)
    await start_a2a_server(agent=agent, agent_executor=executor, host=host, port=port, public_host=config.DEFAULT_PUBLIC_HOST or None)


if __name__ == "__main__":
    main()
