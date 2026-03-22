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


SAMPLE_MARKDOWN = """# 미국 증시 데일리 분석

미국 증시는 단기 강세를 이어가고 있지만 추격 매수의 효율은 낮아졌습니다.

- 대형 기술주가 상대 강세를 유지했습니다
- 장기 금리 부담은 여전히 남아 있습니다
- NVDA와 MSFT의 추가 주도 여부를 확인할 필요가 있습니다
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
        self.assertEqual(payload["title"], "미국 증시 데일리 분석")
        self.assertEqual(payload["summary"], "미국 증시는 단기 강세를 이어가고 있지만 추격 매수의 효율은 낮아졌습니다.")
        self.assertEqual(
            payload["highlights"],
            ["대형 기술주가 상대 강세를 유지했습니다", "장기 금리 부담은 여전히 남아 있습니다", "NVDA와 MSFT의 추가 주도 여부를 확인할 필요가 있습니다"],
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

    def test_build_payload_uses_korean_us_default_title_when_heading_missing(self):
        service = J2WMarketIngestService(_config())

        payload = service.build_payload(
            market_scope="us",
            report_markdown="첫 문단만 있는 시장 메모입니다.",
            report_date=date(2026, 3, 22),
        )

        self.assertEqual(payload["title"], "미국 증시 데일리 분석")

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
