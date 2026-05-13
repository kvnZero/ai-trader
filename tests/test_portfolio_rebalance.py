from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from app.portfolio.rebalance import build_portfolio_rebalance_playbook


class PortfolioRebalancePlaybookTests(TestCase):
    def test_build_portfolio_rebalance_playbook_outputs_action_queue(self) -> None:
        account_state = {
            "cash_pct": 25.0,
            "holdings": [
                {"symbol": "600519", "weight_pct": 18.0, "name": "贵州茅台"},
                {"symbol": "300750", "weight_pct": 12.0, "name": "宁德时代"},
                {"symbol": "000858", "weight_pct": 8.0, "name": "五粮液"},
            ],
        }
        portfolio_summary = SimpleNamespace(
            position_plans=[
                SimpleNamespace(
                    symbol="600519",
                    proposed_weight_pct=3.0,
                    notes=["已有持仓，建议仓位按当前持仓占比净额计算。"],
                ),
                SimpleNamespace(
                    symbol="601318",
                    proposed_weight_pct=6.0,
                    notes=["Position fits remaining budget."],
                ),
            ]
        )
        portfolio_risk_overview = {
            "items": [
                {
                    "symbol": "600519",
                    "portfolio_action": "reduce",
                    "portfolio_action_reason": "High severity events and unresolved high issues are stacked.",
                },
                {
                    "symbol": "300750",
                    "portfolio_action": "trim",
                    "portfolio_action_reason": "Signal lifecycle is invalidated for an active holding.",
                },
                {
                    "symbol": "000858",
                    "portfolio_action": "watch",
                    "portfolio_action_reason": "Open high severity issues require closer monitoring.",
                },
            ]
        }

        report = build_portfolio_rebalance_playbook(
            account_state=account_state,
            portfolio_summary=portfolio_summary,
            portfolio_risk_overview=portfolio_risk_overview,
        )

        self.assertEqual(
            [(item.symbol, item.action, item.target_delta) for item in report.actions],
            [
                ("300750", "trim_reduce", -12.0),
                ("600519", "trim_reduce", -3.0),
                ("601318", "buy_add", 6.0),
                ("000858", "hold_monitor", 0.0),
            ],
        )
        self.assertEqual(report.action_counts["trim_reduce"], 2)
        self.assertEqual(report.action_counts["buy_add"], 1)
        self.assertEqual(report.action_counts["hold_monitor"], 1)
        self.assertEqual(report.action_counts["no_action"], 0)

    def test_build_portfolio_rebalance_playbook_marks_no_action_when_symbol_has_no_plan_or_risk(self) -> None:
        report = build_portfolio_rebalance_playbook(
            account_state={"holdings": [{"symbol": "688981", "weight_pct": 5.0}]},
            portfolio_summary={"position_plans": []},
            portfolio_risk_overview={"items": []},
        )

        self.assertEqual(len(report.actions), 1)
        self.assertEqual(report.actions[0].symbol, "688981")
        self.assertEqual(report.actions[0].action, "no_action")
        self.assertEqual(report.actions[0].target_delta, 0.0)


if __name__ == "__main__":
    import unittest

    unittest.main()
