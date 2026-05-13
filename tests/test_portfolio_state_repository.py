from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from app.persistence import (
    DEFAULT_CASH_ACCOUNT_KEY,
    PortfolioCashRepository,
    PortfolioHoldingRepository,
    init_database,
)


class PortfolioStateRepositoryTests(TestCase):
    def test_holding_crud_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio_state.db"))
            holding_repository = PortfolioHoldingRepository(database)

            created = holding_repository.upsert_holding(
                symbol="600519",
                name="贵州茅台",
                shares=100,
                avg_cost=1500.0,
                last_price=1600.0,
                notes="核心持仓",
            )
            self.assertTrue(created)

            updated = holding_repository.upsert_holding(
                symbol="600519",
                name="贵州茅台",
                shares=120,
                avg_cost=1480.0,
                last_price=1610.0,
                notes="加仓后更新",
            )
            self.assertTrue(updated)

            second_created = holding_repository.upsert_holding(
                symbol="300750",
                name="宁德时代",
                shares=50,
                avg_cost=220.0,
                last_price=None,
                notes=None,
            )
            self.assertTrue(second_created)

            rows = holding_repository.list_rows()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].symbol, "300750")
            self.assertIsNone(rows[0].market_value)

            maotai = holding_repository.get_row("600519")
            assert maotai is not None
            self.assertEqual(maotai.shares, 120.0)
            self.assertEqual(maotai.avg_cost, 1480.0)
            self.assertEqual(maotai.last_price, 1610.0)
            self.assertEqual(maotai.market_value, 193200.0)

            summary = holding_repository.build_summary(cash_balance=50000.0)
            self.assertEqual(summary.holdings_count, 2)
            self.assertEqual(summary.total_shares, 170.0)
            self.assertEqual(summary.total_cost_basis, 188600.0)
            self.assertEqual(summary.total_market_value, 193200.0)
            self.assertEqual(summary.cash_balance, 50000.0)
            self.assertEqual(summary.net_liquidation_value, 243200.0)

            deleted = holding_repository.delete_holding("300750")
            self.assertTrue(deleted)
            self.assertIsNone(holding_repository.get_row("300750"))

    def test_cash_balance_crud(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = init_database(str(Path(tmpdir) / "portfolio_cash.db"))
            cash_repository = PortfolioCashRepository(database)

            created = cash_repository.upsert_balance(balance=100000.0)
            self.assertTrue(created)

            updated = cash_repository.upsert_balance(
                account_key=DEFAULT_CASH_ACCOUNT_KEY,
                balance=120500.0,
            )
            self.assertTrue(updated)

            secondary = cash_repository.upsert_balance(
                account_key="margin",
                balance=25000.0,
            )
            self.assertTrue(secondary)

            default_balance = cash_repository.get_balance()
            assert default_balance is not None
            self.assertEqual(default_balance.balance, 120500.0)

            rows = cash_repository.list_rows()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].account_key, DEFAULT_CASH_ACCOUNT_KEY)
            self.assertEqual(rows[1].account_key, "margin")

            deleted = cash_repository.delete_balance("margin")
            self.assertTrue(deleted)
            self.assertIsNone(cash_repository.get_balance("margin"))


if __name__ == "__main__":
    import unittest

    unittest.main()
