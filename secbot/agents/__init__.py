"""Expert agent registry for secbot.

Authoritative contract: `.trellis/spec/backend/agent-registry-contract.md`.

Each YAML file in this directory declares ONE expert agent. Filename stem ==
agent name == Orchestrator-visible tool name.
"""

from secbot.agents.registry import (
    AgentRegistry,
    AgentRegistryError,
    ExpertAgentSpec,
    load_agent_registry,
)

__all__ = [
    "AgentRegistry",
    "AgentRegistryError",
    "ExpertAgentSpec",
    "load_agent_registry",
]
