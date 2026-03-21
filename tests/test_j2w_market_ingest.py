# -*- coding: utf-8 -*-
"""Unit tests for optional J2W market analysis upload."""
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import Config
from src.services.j2w_market_ingest import J2WMarketIngestService


SAMPLE_MARKDOWN = """# 美股大盘复盘

美股短线强势，但追价性价比一般。

- 科技股相对强势
- 长端利率仍有压力
- 观察 NVDA 与 MSFT 是否继续领涨
"""


def _config(**overrides):
    values = {
        "stock_list": [],
        "j2w_market_analysis_endpoint": "https://j2winvestment.com/api/market-analysis-ingest",
        "j2w_market_analysis_token": "secret-token",
        "j2w_market_analysis_source_url": "https://github.com/wonwoojeon/daily_stock_analysis",
    }
    values.update(overrides)
    return Config(**values)


class TestJ2WMarketIngestService(unittest.TestCase):
    def test_build_payload_extracts_summary_highlights_and_metadata(self):
        service = J2WMarketIngestService(_config())

        payload = service.build_payload(
            market_scope="us",
            report_markdown=SAMPLE_MARKDOWN,
            report_date=date(2026, 3, 22),
            raw_payload={"runner": "github-actions"},
        )

        self.assertEqual(payload["reportDate"], "2026-03-22")
        self.assertEqual(payload["marketScope"], "us")
        self.assertEqual(payload["title"], "美股大盘复盘")
        self.assertEqual(payload["summary"], "美股短线强势，但追价性价比一般。")
        self.assertEqual(
            payload["highlights"],
            ["科技股相对强势", "长端利率仍有压力", "观察 NVDA 与 MSFT 是否继续领涨"],
        )
        self.assertEqual(payload["sourceName"], "daily_stock_analysis")
        self.assertEqual(payload["sourceUrl"], "https://github.com/wonwoojeon/daily_stock_analysis")
        self.assertEqual(payload["rawPayload"]["runner"], "github-actions")

    @mock.patch("src.services.j2w_market_ingest.requests.post")
    def test_publish_market_report_posts_bearer_payload(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"
        service = J2WMarketIngestService(_config())

        ok = service.publish_market_report(
            market_scope="us",
            report_markdown=SAMPLE_MARKDOWN,
            report_date=date(2026, 3, 22),
            raw_payload={"runner": "github-actions"},
        )

        self.assertTrue(ok)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://j2winvestment.com/api/market-analysis-ingest")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(kwargs["json"]["marketScope"], "us")
        self.assertEqual(kwargs["timeout"], 15)

    @mock.patch("src.services.j2w_market_ingest.requests.post")
    def test_publish_market_report_skips_when_not_configured(self, mock_post):
        service = J2WMarketIngestService(
            _config(j2w_market_analysis_endpoint=None, j2w_market_analysis_token=None)
        )

        ok = service.publish_market_report(
            market_scope="us",
            report_markdown=SAMPLE_MARKDOWN,
            report_date=date(2026, 3, 22),
        )

        self.assertFalse(ok)
        mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
