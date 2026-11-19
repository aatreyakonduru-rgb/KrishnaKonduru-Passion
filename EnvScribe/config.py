"""Configuration: everything comes from environment variables. No credentials are hardcoded.

Mirrors the aicoe-agent-utils weather_agent layout. NOTE: names of the aicoe-agent-utils symbols used in
envscribe_agent.py / a2a_factory.py / main.py are taken from the project guide and have NOT been verified against the
submodule (it could not be cloned here). Verify them against aicoe-agent-utils/examples/agents_with_mcp/weather_agent/.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _csv(name: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


# --- LLM provider (default watsonx) ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "watsonx").lower()
WATSONX_APIKEY = os.getenv("WATSONX_APIKEY", "")
WATSONX_URL = os.getenv("WATSONX_URL", "")
WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "")
WATSONX_MODEL_ID = os.getenv("WATSONX_MODEL_ID", "meta-llama/llama-3-3-70b-instruct")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL_ID = os.getenv("OLLAMA_MODEL_ID", "")

# --- MCP servers ---
MCP_SERVER_NAMES = _csv("MCP_SERVER_NAMES")
MCP_SERVER_URLS = _csv("MCP_SERVER_URLS")
MCP_SERVER_TRANSPORT = os.getenv("MCP_SERVER_TRANSPORT", "streamable-http")

# --- A2A server ---
DEFAULT_HOST = os.getenv("DEFAULT_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("DEFAULT_PORT", "8080"))
DEFAULT_PUBLIC_HOST = os.getenv("DEFAULT_PUBLIC_HOST", "")

# --- Web UI ---
UI_HOST = os.getenv("UI_HOST", "127.0.0.1")
UI_PORT = int(os.getenv("UI_PORT", "8090"))

# --- Authentication (both off by default; enabling requires client_id AND client_secret) ---
ENABLE_CLIENT_AUTH = _bool("ENABLE_CLIENT_AUTH")
ENABLE_USER_AUTH = _bool("ENABLE_USER_AUTH")
IBM_TENANT_ID = os.getenv("IBM_TENANT_ID", "")
IBM_INTROSPECT_URL = os.getenv("IBM_INTROSPECT_URL", "")

# --- AgentOps (optional, install on demand: pip install aicoe-agent-utils[agentops]) ---
ENABLE_AGENTOPS = _bool("ENABLE_AGENTOPS")
AGENTOPS_APP_NAME = os.getenv("AGENTOPS_APP_NAME", "envscribe")
AGENTOPS_ENDPOINT = os.getenv("AGENTOPS_ENDPOINT", "")

# --- EnvScribe engine ---
TARGETS_FILE = os.getenv("ENVSCRIBE_TARGETS", "targets.yaml")


def validate() -> list[str]:
    problems = []
    if LLM_PROVIDER == "watsonx" and not (WATSONX_APIKEY and WATSONX_URL and WATSONX_PROJECT_ID):
        problems.append("LLM_PROVIDER=watsonx requires WATSONX_APIKEY, WATSONX_URL and WATSONX_PROJECT_ID")
    if LLM_PROVIDER == "ollama" and not OLLAMA_MODEL_ID:
        problems.append("LLM_PROVIDER=ollama requires OLLAMA_MODEL_ID")
    if len(MCP_SERVER_NAMES) != len(MCP_SERVER_URLS):
        problems.append("MCP_SERVER_NAMES and MCP_SERVER_URLS must have the same number of entries")
    if (ENABLE_CLIENT_AUTH or ENABLE_USER_AUTH) and not (IBM_TENANT_ID and IBM_INTROSPECT_URL):
        problems.append("auth enabled but IBM_TENANT_ID / IBM_INTROSPECT_URL missing")
    return problems
