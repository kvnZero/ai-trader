"""Independent trader agent capability package."""

from app.modules.trader_agent.contracts import (
    TraderAgentInput,
    TraderSentimentSummary,
    TraderTechnicalSummary,
)
from app.modules.trader_agent.service import (
    DeterministicTraderAgentRecommender,
    TraderAgentInputAssembler,
    TraderAgentRecommender,
    TraderAgentService,
    build_default_trader_agent_service,
)

__all__ = [
    "DeterministicTraderAgentRecommender",
    "TraderAgentInput",
    "TraderAgentInputAssembler",
    "TraderAgentRecommender",
    "TraderAgentService",
    "TraderSentimentSummary",
    "TraderTechnicalSummary",
    "build_default_trader_agent_service",
]
