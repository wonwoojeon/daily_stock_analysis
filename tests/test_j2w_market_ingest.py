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


WATCHLIST_ITEMS = [
    {
        "symbol": "TSLA",
        "name": "Tesla",
        "stance": "관심",
        "summary": "전기차 수요 회복과 마진 안정 여부를 함께 확인합니다.",
    },
    {
        "symbol": "SOXL",
        "name": "Direxion Daily Semiconductor Bull 3X Shares",
        "stance": "경계",
        "summary": "반도체 강세 추종용이지만 변동성이 커서 무리한 추격은 피합니다.",
    },
]

LIVE_ITEMS = [
    {
        "symbol": "TSLA",
        "name": "Tesla, Inc.",
        "price": 367.96,
        "change": -23.24,
        "changePercent": -5.94,
        "currency": "USD",
        "sessionLabel": "장마감",
        "refreshedAt": "2026-03-23T01:47:00.000Z",
        "news": [
            {
                "title": "Tesla tests new chip capacity plan",
                "url": "https://example.com/tesla-chip",
                "source": "Yahoo Finance",
                "publishedAt": "2026-03-23T01:20:00.000Z",
            }
        ],
    },
    {
        "symbol": "SOXL",
        "name": "SOXL",
        "price": 61.24,
        "change": -2.18,
        "changePercent": -3.44,
        "currency": "USD",
        "sessionLabel": "장마감",
        "refreshedAt": "2026-03-23T01:47:00.000Z",
        "news": [],
    },
]


def _config(**overrides):
    values = {
        "stock_list": [],
        "j2w_market_analysis_endpoint": "https://j2winvestment.com/api/market-analysis-ingest",
        "j2w_market_analysis_token": "secret-token",
        "j2w_market_analysis_source_url": "https://github.com/wonwoojeon/daily_stock_analysis",
        "j2w_market_watchlist_endpoint": None,
        "j2w_market_watchlist_live_endpoint": None,
    }
    values.update(overrides)
    return Config(**values)


class TestJ2WMarketIngestService(unittest.TestCase):
    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_live_items", return_value=LIVE_ITEMS)
    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_items", return_value=WATCHLIST_ITEMS)
    def test_build_payload_prefers_watchlist_tickers_with_live_overlay(self, _mock_watchlist, _mock_live):
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
        self.assertEqual(payload["rawPayload"]["watchlistMode"], "persistent")
        self.assertEqual(payload["rawPayload"]["watchlistTickerCount"], 2)
        self.assertEqual([ticker["symbol"] for ticker in payload["tickers"]], ["TSLA", "SOXL"])
        self.assertEqual(payload["tickers"][0]["adminNote"], WATCHLIST_ITEMS[0]["summary"])
        self.assertEqual(payload["tickers"][0]["price"], 367.96)
        self.assertEqual(payload["tickers"][0]["changePercent"], -5.94)
        self.assertEqual(payload["tickers"][0]["news"][0]["title"], "Tesla tests new chip capacity plan")
        self.assertIn("TSLA", payload["tickers"][0]["commentary"])

    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_live_items", return_value=[])
    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_items", return_value=[])
    def test_build_payload_falls_back_to_report_tickers_without_watchlist(self, _mock_watchlist, _mock_live):
        service = J2WMarketIngestService(_config())

        payload = service.build_payload(
            market_scope="us",
            report_markdown=SAMPLE_MARKDOWN,
            report_date=date(2026, 3, 22),
        )

        self.assertEqual([ticker["symbol"] for ticker in payload["tickers"]], ["NVDA", "MSFT"])
        self.assertNotIn("watchlistMode", payload["rawPayload"])

    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_live_items", return_value=[])
    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_items", return_value=[])
    @mock.patch("src.services.j2w_market_ingest.requests.post")
    def test_publish_market_report_posts_bearer_payload(self, mock_post, _mock_watchlist, _mock_live):
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

    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_live_items", return_value=[])
    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_items", return_value=[])
    def test_build_payload_uses_korean_us_default_title_when_heading_missing(self, _mock_watchlist, _mock_live):
        service = J2WMarketIngestService(_config())

        payload = service.build_payload(
            market_scope="us",
            report_markdown="첫 문단만 있는 시장 메모입니다.",
            report_date=date(2026, 3, 22),
        )

        self.assertEqual(payload["title"], "미국 증시 데일리 분석")

    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_live_items", return_value=[])
    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_items", return_value=[])
    def test_build_payload_splits_long_summary_into_multiple_highlights(self, _mock_watchlist, _mock_live):
        service = J2WMarketIngestService(_config())
        markdown = """# 미국 증시 데일리 분석

S&P 500은 6506선에서 1.51% 하락하며 6500선 심리적 지지를 테스트했다. 나스닥은 2.01% 급락해 21600선에서 마감하며 기술주 중심의 약세가 두드러졌다. 다우존스는 0.96% 하락에 그쳐 대형 우량주 중심의 상대적 강세를 보였다. VIX는 11% 넘게 급등하며 위험회피 심리를 강화했다.

| 지수 | 현재가 | 등락률 | 거래대금 |
|------|--------|--------|----------|
"""

        payload = service.build_payload(
            market_scope="us",
            report_markdown=markdown,
            report_date=date(2026, 3, 23),
        )

        self.assertEqual(
            payload["highlights"],
            [
                "S&P 500은 6506선에서 1.51% 하락하며 6500선 심리적 지지를 테스트했다.",
                "나스닥은 2.01% 급락해 21600선에서 마감하며 기술주 중심의 약세가 두드러졌다.",
                "다우존스는 0.96% 하락에 그쳐 대형 우량주 중심의 상대적 강세를 보였다.",
                "VIX는 11% 넘게 급등하며 위험회피 심리를 강화했다.",
            ],
        )

    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_live_items", return_value=[])
    @mock.patch.object(J2WMarketIngestService, "_fetch_watchlist_items", return_value=[])
    def test_build_payload_ignores_markdown_table_rows_in_bullet_highlights(self, _mock_watchlist, _mock_live):
        service = J2WMarketIngestService(_config())
        markdown = """# 미국 증시 데일리 분석

단기 리스크 관리가 필요한 장입니다.

- S&P 500은 6500선 지지 확인이 먼저입니다.
- | 지수 | 현재가 | 등락률 |
- |------|--------|--------|
- VIX 급등으로 방어 심리가 강화됐습니다.
"""

        payload = service.build_payload(
            market_scope="us",
            report_markdown=markdown,
            report_date=date(2026, 3, 23),
        )

        self.assertEqual(
            payload["highlights"],
            [
                "S&P 500은 6500선 지지 확인이 먼저입니다.",
                "VIX 급등으로 방어 심리가 강화됐습니다.",
            ],
        )

    def test_resolves_watchlist_endpoints_from_ingest_endpoint(self):
        service = J2WMarketIngestService(_config())

        self.assertEqual(
            service._resolve_watchlist_endpoint(),
            "https://j2winvestment.com/api/market-analysis-watchlist",
        )
        self.assertEqual(
            service._resolve_watchlist_live_endpoint(),
            "https://j2winvestment.com/api/market-analysis-watchlist/live",
        )

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
