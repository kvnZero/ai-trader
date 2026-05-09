from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from app.domain import CompanyMatch, SentimentItem
from app.modules.entity_mapping.dictionary import (
    CompanyDictionary,
    CompanyDictionaryEntry,
    build_default_company_dictionary,
)
from app.modules.entity_mapping.normalization import (
    FieldName,
    NormalizedSentimentItem,
)

_CATEGORY_WEIGHTS = {
    "symbol": 0.78,
    "company_name": 0.72,
    "alias": 0.58,
    "industry": 0.22,
    "theme": 0.18,
}
_CATEGORY_CAPS = {
    "symbol": 0.82,
    "company_name": 0.76,
    "alias": 0.66,
    "industry": 0.28,
    "theme": 0.24,
}
_FIELD_MULTIPLIERS: dict[FieldName, float] = {
    "title": 1.00,
    "content": 0.90,
    "tags": 1.08,
    "raw_reference": 0.78,
}
_CATEGORY_LABELS = {
    "symbol": "symbol",
    "company_name": "company name",
    "alias": "alias",
    "industry": "industry keyword",
    "theme": "theme keyword",
}
_DIRECT_CATEGORIES = {"symbol", "company_name", "alias"}
_CONTEXT_CATEGORIES = {"industry", "theme"}


@dataclass(frozen=True, slots=True)
class _KeywordEvidence:
    category: str
    keyword: str
    fields: tuple[FieldName, ...]
    contribution: float
    shared_count: int


class EntityMappingService:
    """Deterministic company matcher for normalized sentiment items."""

    def __init__(self, company_dictionary: CompanyDictionary | None = None):
        self.company_dictionary = company_dictionary or build_default_company_dictionary()

    def map_sentiment_item(
        self,
        item: SentimentItem,
        *,
        min_confidence: float = 0.20,
        max_matches: int = 5,
    ) -> list[CompanyMatch]:
        normalized_item = NormalizedSentimentItem.from_item(item)
        matches: list[CompanyMatch] = []

        for entry in self.company_dictionary.entries:
            company_match = self._match_entry(entry=entry, item=normalized_item)
            if company_match is None or company_match.confidence < min_confidence:
                continue
            matches.append(company_match)

        matches.sort(key=lambda match: (-match.confidence, match.company.symbol))
        return matches[:max_matches]

    def map_sentiment_items(
        self,
        items: Iterable[SentimentItem],
        *,
        min_confidence: float = 0.20,
        max_matches: int = 5,
    ) -> list[list[CompanyMatch]]:
        return [
            self.map_sentiment_item(
                item,
                min_confidence=min_confidence,
                max_matches=max_matches,
            )
            for item in items
        ]

    def _match_entry(
        self,
        *,
        entry: CompanyDictionaryEntry,
        item: NormalizedSentimentItem,
    ) -> CompanyMatch | None:
        category_scores: dict[str, float] = defaultdict(float)
        evidences: list[_KeywordEvidence] = []

        for category, keywords in self.company_dictionary.iter_keywords(entry).items():
            for keyword in keywords:
                fields = item.find_fields_for_keyword(keyword)
                if not fields:
                    continue

                shared_count = self.company_dictionary.shared_count(category, keyword)
                contribution = self._calculate_contribution(
                    category=category,
                    fields=fields,
                    shared_count=shared_count,
                )
                if contribution <= 0:
                    continue

                remaining = _CATEGORY_CAPS[category] - category_scores[category]
                if remaining <= 0:
                    continue

                applied = min(contribution, remaining)
                category_scores[category] += applied
                evidences.append(
                    _KeywordEvidence(
                        category=category,
                        keyword=keyword,
                        fields=fields,
                        contribution=applied,
                        shared_count=shared_count,
                    )
                )

        if not evidences:
            return None

        confidence = self._finalize_confidence(
            category_scores=category_scores,
            evidences=evidences,
        )
        evidence_lines = self._build_evidence(evidences=evidences)
        return CompanyMatch(
            company=entry.company,
            confidence=confidence,
            evidence=evidence_lines,
        )

    def _calculate_contribution(
        self,
        *,
        category: str,
        fields: tuple[FieldName, ...],
        shared_count: int,
    ) -> float:
        field_multiplier = max(_FIELD_MULTIPLIERS[field] for field in fields)
        cross_field_bonus = min(0.06, 0.03 * (len(fields) - 1))
        specificity = self._specificity_factor(category=category, shared_count=shared_count)
        return _CATEGORY_WEIGHTS[category] * field_multiplier * specificity + cross_field_bonus

    def _finalize_confidence(
        self,
        *,
        category_scores: dict[str, float],
        evidences: list[_KeywordEvidence],
    ) -> float:
        confidence = sum(category_scores.values())
        direct_categories = {evidence.category for evidence in evidences if evidence.category in _DIRECT_CATEGORIES}
        context_categories = {evidence.category for evidence in evidences if evidence.category in _CONTEXT_CATEGORIES}

        if direct_categories and context_categories:
            confidence += 0.10
        if len(direct_categories) >= 2:
            confidence += 0.06
        if len(context_categories) >= 2:
            confidence += 0.04

        if not direct_categories:
            confidence = min(confidence, 0.46)

        alias_only = direct_categories == {"alias"}
        ambiguous_alias_only = alias_only and all(
            evidence.shared_count > 1
            for evidence in evidences
            if evidence.category == "alias"
        )
        if ambiguous_alias_only and not context_categories:
            confidence = min(confidence, 0.38)

        if any(evidence.shared_count > 1 for evidence in evidences) and not (
            {"symbol", "company_name"} & direct_categories
        ):
            confidence -= 0.04

        return round(max(0.0, min(confidence, 1.0)), 3)

    def _build_evidence(self, *, evidences: list[_KeywordEvidence]) -> list[str]:
        ordered_evidences = sorted(
            evidences,
            key=lambda evidence: (-evidence.contribution, evidence.category, evidence.keyword),
        )

        evidence_lines = [
            self._format_evidence_line(evidence)
            for evidence in ordered_evidences[:5]
        ]
        direct_categories = {evidence.category for evidence in evidences if evidence.category in _DIRECT_CATEGORIES}
        context_categories = {evidence.category for evidence in evidences if evidence.category in _CONTEXT_CATEGORIES}

        if direct_categories and context_categories:
            evidence_lines.append("direct company evidence is reinforced by industry/theme context")
        elif not direct_categories:
            evidence_lines.append("mapping relies on sector/theme context without a direct company mention")
        elif any(evidence.shared_count > 1 for evidence in evidences):
            evidence_lines.append("shared dictionary keywords reduce certainty for this mapping")

        return evidence_lines

    def _format_evidence_line(self, evidence: _KeywordEvidence) -> str:
        fields = "/".join(evidence.fields)
        line = f"{_CATEGORY_LABELS[evidence.category]} match '{evidence.keyword}' in {fields}"
        if evidence.shared_count > 1:
            line += f"; keyword is shared by {evidence.shared_count} companies"
        return line

    def _specificity_factor(self, *, category: str, shared_count: int) -> float:
        if shared_count <= 1:
            return 1.00

        if category == "alias":
            if shared_count == 2:
                return 0.72
            if shared_count == 3:
                return 0.58
            return 0.44

        if category == "industry":
            if shared_count == 2:
                return 0.66
            if shared_count == 3:
                return 0.52
            return 0.36

        if category == "theme":
            if shared_count == 2:
                return 0.62
            if shared_count == 3:
                return 0.48
            return 0.34

        return 1.00


def build_default_entity_mapping_service() -> EntityMappingService:
    return EntityMappingService(company_dictionary=build_default_company_dictionary())
