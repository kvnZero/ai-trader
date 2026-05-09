from __future__ import annotations


class TechnicalAnalysisError(Exception):
    """Base error for the technical analysis capability."""


class TechnicalAnalysisValidationError(TechnicalAnalysisError):
    """Raised when normalized market bars are missing or inconsistent."""
