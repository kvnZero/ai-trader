from __future__ import annotations

from dataclasses import dataclass

from app.persistence.db import Database


DEFAULT_PORTFOLIO_PROFILE = "default"


@dataclass(frozen=True, slots=True)
class PortfolioSettingsRow:
    profile: str
    max_total_risk_budget_pct: float
    max_single_position_pct: float
    max_industry_exposure_pct: float
    max_theme_overlap_pct: float


class PortfolioSettingsRepository:
    def __init__(self, database: Database):
        self.database = database

    def ensure_default(self) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_settings (
                    profile,
                    max_total_risk_budget_pct,
                    max_single_position_pct,
                    max_industry_exposure_pct,
                    max_theme_overlap_pct
                ) VALUES (?, 100.0, 20.0, 35.0, 45.0)
                ON CONFLICT(profile) DO NOTHING
                """,
                (DEFAULT_PORTFOLIO_PROFILE,),
            )
            conn.commit()

    def get_settings(self, profile: str = DEFAULT_PORTFOLIO_PROFILE) -> PortfolioSettingsRow:
        self.ensure_default()
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT profile, max_total_risk_budget_pct, max_single_position_pct,
                       max_industry_exposure_pct, max_theme_overlap_pct
                FROM portfolio_settings
                WHERE profile = ?
                LIMIT 1
                """,
                (profile,),
            ).fetchone()
        if row is None:
            return PortfolioSettingsRow(
                profile=profile,
                max_total_risk_budget_pct=100.0,
                max_single_position_pct=20.0,
                max_industry_exposure_pct=35.0,
                max_theme_overlap_pct=45.0,
            )
        return PortfolioSettingsRow(
            profile=row["profile"],
            max_total_risk_budget_pct=float(row["max_total_risk_budget_pct"]),
            max_single_position_pct=float(row["max_single_position_pct"]),
            max_industry_exposure_pct=float(row["max_industry_exposure_pct"]),
            max_theme_overlap_pct=float(row["max_theme_overlap_pct"]),
        )

    def update_settings(
        self,
        *,
        max_total_risk_budget_pct: float,
        max_single_position_pct: float,
        max_industry_exposure_pct: float,
        max_theme_overlap_pct: float,
        profile: str = DEFAULT_PORTFOLIO_PROFILE,
    ) -> bool:
        self.ensure_default()
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE portfolio_settings
                SET max_total_risk_budget_pct = ?,
                    max_single_position_pct = ?,
                    max_industry_exposure_pct = ?,
                    max_theme_overlap_pct = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE profile = ?
                """,
                (
                    max_total_risk_budget_pct,
                    max_single_position_pct,
                    max_industry_exposure_pct,
                    max_theme_overlap_pct,
                    profile,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0
