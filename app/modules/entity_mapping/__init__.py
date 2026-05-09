"""Deterministic entity mapping for A-share sentiment items."""

from app.modules.entity_mapping.dictionary import (
    CompanyDictionary,
    CompanyDictionaryEntry,
    build_default_company_dictionary,
)
from app.modules.entity_mapping.service import (
    EntityMappingService,
    build_default_entity_mapping_service,
)

__all__ = [
    "CompanyDictionary",
    "CompanyDictionaryEntry",
    "EntityMappingService",
    "build_default_company_dictionary",
    "build_default_entity_mapping_service",
]
