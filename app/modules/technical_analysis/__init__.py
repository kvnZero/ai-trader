"""Deterministic technical analysis capability package."""

from app.modules.technical_analysis.contracts import (
    MarketRegime,
    MarketRegimeAssessment,
    TechnicalAnalysisResult,
    TechnicalIndicatorSnapshot,
)
from app.modules.technical_analysis.errors import (
    TechnicalAnalysisError,
    TechnicalAnalysisValidationError,
)
from app.modules.technical_analysis.service import (
    TechnicalAnalysisService,
    build_default_technical_analysis_service,
)

__all__ = [
    "TechnicalAnalysisError",
    "MarketRegime",
    "MarketRegimeAssessment",
    "TechnicalAnalysisResult",
    "TechnicalAnalysisService",
    "TechnicalAnalysisValidationError",
    "TechnicalIndicatorSnapshot",
    "build_default_technical_analysis_service",
]
