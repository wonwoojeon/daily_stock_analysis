# -*- coding: utf-8 -*-
"""Tests for market strategy blueprints."""

import importlib
import sys
import unittest
from unittest.mock import MagicMock, patch

from src.core.market_strategy import get_market_strategy_blueprint


class TestMarketStrategyBlueprint(unittest.TestCase):
    """Validate CN/US strategy blueprint basics."""

    def test_cn_blueprint_contains_action_framework(self):
        blueprint = get_market_strategy_blueprint("cn")
        block = blueprint.to_prompt_block()

        self.assertIn("A股市场三段式复盘策略", block)
        self.assertIn("Action Framework", block)
        self.assertIn("进攻", block)

    def test_us_blueprint_contains_regime_strategy(self):
        blueprint = get_market_strategy_blueprint("us")
        block = blueprint.to_prompt_block()

        self.assertIn("US Market Regime Strategy", block)
        self.assertIn("Risk-on", block)
        self.assertIn("Macro & Flows", block)


class TestMarketAnalyzerStrategyPrompt(unittest.TestCase):
    """Validate strategy section is injected into prompt/report."""

    def _build_prompt(self, region: str) -> str:
        fake_modules = {
            "pandas": MagicMock(),
            "newspaper": MagicMock(),
            "src.search_service": MagicMock(SearchService=MagicMock()),
            "data_provider.base": MagicMock(DataFetcherManager=MagicMock()),
        }

        sys.modules.pop("src.market_analyzer", None)
        with patch.dict(sys.modules, fake_modules):
            module = importlib.import_module("src.market_analyzer")
            analyzer = module.MarketAnalyzer(region=region)
            prompt = analyzer._build_review_prompt(module.MarketOverview(date="2026-02-24"), [])
        sys.modules.pop("src.market_analyzer", None)
        return prompt

    def test_cn_prompt_contains_strategy_plan_section(self):
        prompt = self._build_prompt("cn")

        self.assertIn("策略计划", prompt)
        self.assertIn("A股市场三段式复盘策略", prompt)

    def test_us_prompt_contains_strategy_plan_section(self):
        prompt = self._build_prompt("us")

        self.assertIn("대응 아이디어", prompt)
        self.assertIn("US Market Regime Strategy", prompt)

    def test_us_prompt_uses_korean_market_title_template(self):
        prompt = self._build_prompt("us")

        self.assertIn("미국 증시 데일리 분석", prompt)
        self.assertNotIn("US Market Recap", prompt)


if __name__ == "__main__":
    unittest.main()
