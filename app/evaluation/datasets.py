from __future__ import annotations


def build_sample_evaluation_cases() -> list[dict[str, object]]:
    return [
        {
            "case_id": "trend-bullish-confirmed",
            "symbol": "600519",
            "label": "趋势延续且舆情稳定",
            "market_regime": "trend",
            "expected_action": "buy",
            "expected_quality": "high",
            "inputs": {
                "technical": ["ma_alignment_bullish", "volume_supportive", "trend_follow_through"],
                "sentiment": ["positive_company_mentions", "no_fresh_negative_news"],
                "risk_flags": [],
            },
            "review_focus": "确认系统在趋势型环境下不会无故降级为 no-trade。",
        },
        {
            "case_id": "panic-no-trade",
            "symbol": "300750",
            "label": "恐慌波动与确认度不足",
            "market_regime": "panic",
            "expected_action": "avoid",
            "expected_quality": "low",
            "inputs": {
                "technical": ["breakdown_risk", "high_volatility", "weak_confirmation"],
                "sentiment": ["mixed_news_flow"],
                "risk_flags": ["risk_control_should_override"],
            },
            "review_focus": "验证 panic + low confidence 时系统会明确 no-trade / avoid。",
        },
        {
            "case_id": "low-liquidity-downgrade",
            "symbol": "688981",
            "label": "信号存在但流动性偏弱",
            "market_regime": "range",
            "expected_action": "watch",
            "expected_quality": "medium",
            "inputs": {
                "technical": ["candidate_breakout"],
                "sentiment": ["theme_discussion_present"],
                "risk_flags": ["low_liquidity", "slippage_risk"],
            },
            "review_focus": "验证流动性守门会把激进动作降级成 watch。",
        },
        {
            "case_id": "policy-theme-rebound",
            "symbol": "002594",
            "label": "政策催化下的反弹观察",
            "market_regime": "rebound",
            "expected_action": "watch",
            "expected_quality": "medium",
            "inputs": {
                "technical": ["rebound_attempt", "short_term_improvement"],
                "sentiment": ["policy_support", "crowded_theme_risk"],
                "risk_flags": ["needs_multitimeframe_confirmation"],
            },
            "review_focus": "验证反弹初期不会被过度放大成高置信 buy。",
        },
    ]
