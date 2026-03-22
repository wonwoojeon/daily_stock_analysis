# -*- coding: utf-8 -*-
"""Regression test for J2W upload in market-review-only mode."""

import argparse
import os
import sys
import types
import unittest
import importlib
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.config import Config


SAMPLE_MARKDOWN = "# 미국 증시 데일리 분석\n\n시장 변동성이 커졌지만 한국어 요약 리포트는 정상 생성됐습니다."


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        debug=False,
        dry_run=False,
        stocks=None,
        no_notify=False,
        single_notify=False,
        workers=None,
        schedule=False,
        no_run_immediately=False,
        market_review=True,
        no_market_review=False,
        force_run=True,
        webui=False,
        webui_only=False,
        serve=False,
        serve_only=False,
        port=8000,
        host="0.0.0.0",
        no_context_snapshot=False,
        backtest=False,
        backtest_code=None,
        backtest_days=None,
        backtest_force=False,
    )


def _config() -> Config:
    return Config(
        stock_list=[],
        log_dir="logs",
        market_review_region="us",
        j2w_market_analysis_endpoint="https://j2winvestment.com/api/market-analysis-ingest",
        j2w_market_analysis_token="secret-token",
        j2w_market_analysis_source_url="https://github.com/wonwoojeon/daily_stock_analysis",
    )


class DummyGeminiAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key

    def is_available(self):
        return True


class DummyNotificationService:
    pass


class DummySearchService:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def _load_main_module():
    stub_modules = {
        "data_provider.base": types.SimpleNamespace(canonical_stock_code=lambda code: code),
        "src.core.pipeline": types.SimpleNamespace(StockAnalysisPipeline=object),
        "src.core.market_review": types.SimpleNamespace(run_market_review=lambda **kwargs: None),
        "src.webui_frontend": types.SimpleNamespace(prepare_webui_frontend_assets=lambda: True),
    }

    with mock.patch.dict(sys.modules, stub_modules, clear=False):
        sys.modules.pop("main", None)
        return importlib.import_module("main")


class TestMarketReviewOnlyUpload(unittest.TestCase):
    def test_market_review_only_publishes_report_to_j2w(self):
        main_module = _load_main_module()
        publish_mock = mock.Mock(return_value=True)
        fake_ingest_service = mock.Mock()
        fake_ingest_service.publish_market_report = publish_mock

        fake_modules = {
            "src.analyzer": types.SimpleNamespace(GeminiAnalyzer=DummyGeminiAnalyzer),
            "src.core.market_review": types.SimpleNamespace(run_market_review=mock.Mock(return_value=SAMPLE_MARKDOWN)),
            "src.notification": types.SimpleNamespace(NotificationService=DummyNotificationService),
            "src.search_service": types.SimpleNamespace(SearchService=DummySearchService),
        }

        with mock.patch.dict(sys.modules, fake_modules, clear=False):
            with mock.patch.object(main_module, "parse_arguments", return_value=_args()):
                with mock.patch.object(main_module, "get_config", return_value=_config()):
                    with mock.patch.object(main_module, "setup_logging"):
                        with mock.patch.object(main_module, "J2WMarketIngestService", return_value=fake_ingest_service):
                            exit_code = main_module.main()
        sys.modules.pop("main", None)

        self.assertEqual(exit_code, 0)
        publish_mock.assert_called_once()
        _, kwargs = publish_mock.call_args
        self.assertEqual(kwargs["market_scope"], "us")
        self.assertEqual(kwargs["report_markdown"], SAMPLE_MARKDOWN)
        self.assertEqual(kwargs["title"], None)


if __name__ == "__main__":
    unittest.main()
