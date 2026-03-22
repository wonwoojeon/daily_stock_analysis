# -*- coding: utf-8 -*-
"""Optional J2W market analysis uploader."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests

from src.config import Config, get_config

logger = logging.getLogger(__name__)


class J2WMarketIngestService:
    """Build and upload market-review payloads to the J2W ingest API."""

    DEFAULT_SOURCE_NAME = "daily_stock_analysis"
    DEFAULT_SOURCE_URL = "https://github.com/wonwoojeon/daily_stock_analysis"
    _US_TICKER_STOPWORDS = {
        "A", "AI", "API", "CPI", "ETF", "FOMC", "GDP", "IPO", "MA", "NAV", "PE", "PS",
        "USD", "US", "QQQ", "SPY", "VIX",
    }

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()

    def is_configured(self) -> bool:
        return bool(
            getattr(self.config, "j2w_market_analysis_endpoint", None)
            and getattr(self.config, "j2w_market_analysis_token", None)
        )

    def build_payload(
        self,
        *,
        market_scope: str,
        report_markdown: str,
        report_date: Optional[date] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        text = (report_markdown or "").strip()
        if not text:
            raise ValueError("report_markdown is required")

        normalized_scope = (market_scope or "us").strip().lower()
        normalized_date = (report_date or datetime.now().date()).isoformat()
        normalized_title = (title or self._extract_title(text, normalized_scope)).strip()
        summary = self._extract_summary(text, normalized_title)
        highlights = self._extract_highlights(text, summary)
        tickers = self._extract_tickers(text)
        metadata = {
            "provider": self.DEFAULT_SOURCE_NAME,
            "marketScope": normalized_scope,
        }
        if raw_payload:
            metadata.update(raw_payload)

        return {
            "reportDate": normalized_date,
            "marketScope": normalized_scope,
            "title": normalized_title,
            "summary": summary,
            "highlights": highlights,
            "tickers": tickers,
            "sourceName": self.DEFAULT_SOURCE_NAME,
            "sourceUrl": getattr(self.config, "j2w_market_analysis_source_url", None) or self.DEFAULT_SOURCE_URL,
            "rawPayload": metadata,
        }

    def publish_market_report(
        self,
        *,
        market_scope: str,
        report_markdown: str,
        report_date: Optional[date] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
    ) -> bool:
        if not self.is_configured():
            logger.info("J2W market ingest skipped: endpoint/token not configured")
            return False

        text = (report_markdown or "").strip()
        if not text:
            logger.info("J2W market ingest skipped: empty market report")
            return False

        payload = self.build_payload(
            market_scope=market_scope,
            report_markdown=text,
            report_date=report_date,
            raw_payload=raw_payload,
            title=title,
        )
        endpoint = self.config.j2w_market_analysis_endpoint
        headers = {
            "Authorization": f"Bearer {self.config.j2w_market_analysis_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=15)
        except requests.RequestException as exc:
            logger.warning("J2W market ingest request failed: %s", exc)
            return False

        if 200 <= response.status_code < 300:
            logger.info("J2W market ingest uploaded successfully: %s", payload["reportDate"])
            return True

        logger.warning(
            "J2W market ingest rejected payload: status=%s body=%s",
            response.status_code,
            (response.text or "")[:300],
        )
        return False

    def _extract_title(self, markdown_text: str, market_scope: str) -> str:
        for raw_line in markdown_text.splitlines():
            line = raw_line.strip()
            if line.startswith("#"):
                title = self._clean_text(line.lstrip("#").strip())
                if title:
                    return title
        defaults = {
            "cn": "중국 증시 데일리 분석",
            "us": "미국 증시 데일리 분석",
            "both": "글로벌 증시 데일리 분석",
        }
        return defaults.get(market_scope, "시장 데일리 분석")

    def _extract_summary(self, markdown_text: str, fallback_title: str) -> str:
        for line in self._iter_content_lines(markdown_text):
            if self._is_bullet_line(line):
                continue
            return self._clean_text(line)
        return fallback_title

    def _extract_highlights(self, markdown_text: str, summary: str) -> List[str]:
        highlights: List[str] = []
        for line in markdown_text.splitlines():
            stripped = line.strip()
            if not self._is_bullet_line(stripped):
                continue
            cleaned = self._clean_text(re.sub(r"^[-*+]\s+", "", stripped))
            if cleaned:
                highlights.append(cleaned)

        if not highlights:
            for line in self._iter_content_lines(markdown_text):
                cleaned = self._clean_text(line)
                if cleaned and cleaned != summary:
                    highlights.append(cleaned)
                if len(highlights) >= 3:
                    break

        deduped: List[str] = []
        for item in highlights:
            if item not in deduped:
                deduped.append(item)
        return deduped[:5]

    def _extract_tickers(self, markdown_text: str) -> List[Dict[str, str]]:
        seen: List[str] = []
        for code in re.findall(r"\b\d{6}\b", markdown_text):
            if code not in seen:
                seen.append(code)
        for ticker in re.findall(r"(?<![A-Z])\$?([A-Z]{2,5})(?![A-Z])", markdown_text):
            if ticker in self._US_TICKER_STOPWORDS:
                continue
            if ticker not in seen:
                seen.append(ticker)
        return [{"symbol": symbol} for symbol in seen[:6]]

    def _iter_content_lines(self, markdown_text: str) -> List[str]:
        lines: List[str] = []
        for raw_line in markdown_text.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped == "---":
                continue
            if stripped.startswith("#") or stripped.startswith(">"):
                continue
            lines.append(stripped)
        return lines

    def _is_bullet_line(self, line: str) -> bool:
        return bool(re.match(r"^[-*+]\s+", line.strip()))

    def _clean_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
        cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()
