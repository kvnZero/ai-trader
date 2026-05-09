"""Independent recommendation engine capability package."""

from app.modules.recommendation_engine.contracts import (
    RecommendationComponentScore,
    RecommendationDecisionTrace,
)
from app.modules.recommendation_engine.service import (
    RecommendationBundle,
    RecommendationEngineService,
    build_default_recommendation_engine_service,
)

__all__ = [
    "RecommendationBundle",
    "RecommendationComponentScore",
    "RecommendationDecisionTrace",
    "RecommendationEngineService",
    "build_default_recommendation_engine_service",
]
