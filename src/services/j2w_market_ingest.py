# -*- coding: utf-8 -*-
"""Optional J2W market analysis uploader."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

from src.config import Config, get_config

logger = logging.getLogger(__name__)


class J2WMarketIngestService:
    """Build and upload market-review payloads to the J2W ingest API."""

    DEFAULT_SOURCE_NAME = "daily_stock_analysis"
    DEFAULT_SOURCE_URL = "https://github.com/wonwoojeon/daily_stock_analysis"
    DEFAULT_WATCHLIST_PATH = "/api/market-analysis-watchlist"
    DEFAULT_WATCHLIST_LIVE_PATH = "/api/market-analysis-watchlist/live"
    PUBLIC_HEADERS = {
        "Accept": "application/json",
        "User-Agent": "daily_stock_analysis/1.0",
    }
    _US_TICKER_STOPWORDS = {
        "A", "AI", "API", "CPI", "ETF", "FOMC", "GDP", "IPO", "MA", "NAV", "PE", "PS",
        "USD", "US", "QQQ", "SPY", "VIX",
    }
    _CAUTION_TOKENS = ("하락", "약세", "변동성", "경계", "부담", "리스크", "위험회피", "조정", "불안")
    _CONSTRUCTIVE_TOKENS = ("강세", "상승", "반등", "확장", "회복", "모멘텀", "주도", "관심")

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
        tickers = self._build_watchlist_tickers(
            market_scope=normalized_scope,
            report_markdown=text,
            report_summary=summary,
            highlights=highlights,
        )
        using_watchlist = bool(tickers)
        if not tickers:
            tickers = self._extract_tickers(text)

        metadata = {
            "provider": self.DEFAULT_SOURCE_NAME,
            "marketScope": normalized_scope,
        }
        if using_watchlist:
            metadata["watchlistMode"] = "persistent"
            metadata["watchlistTickerCount"] = len(tickers)
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

    def _build_watchlist_tickers(
        self,
        *,
        market_scope: str,
        report_markdown: str,
        report_summary: str,
        highlights: List[str],
    ) -> List[Dict[str, Any]]:
        if market_scope != "us":
            return []

        watchlist_items = self._fetch_watchlist_items()
        if not watchlist_items:
            return []

        live_by_symbol = {
            item.get("symbol", "").strip().upper(): item
            for item in self._fetch_watchlist_live_items()
            if item.get("symbol")
        }
        market_tone = self._infer_market_tone(report_summary, highlights)
        tickers: List[Dict[str, Any]] = []

        for item in watchlist_items[:6]:
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            live_item = live_by_symbol.get(symbol, {})
            name = self._clean_text(str(item.get("name") or live_item.get("name") or "")) or None
            stance = self._clean_text(str(item.get("stance") or live_item.get("stance") or "")) or None
            admin_note = self._clean_text(str(item.get("summary") or live_item.get("adminNote") or "")) or None
            report_context = self._extract_ticker_context(report_markdown, symbol, name)
            ticker_summary = report_context or admin_note or self._build_summary_fallback(symbol, market_tone)
            commentary = self._build_watchlist_commentary(
                symbol=symbol,
                stance=stance,
                market_tone=market_tone,
                report_context=report_context,
            )

            ticker_payload = self._strip_empty_fields(
                {
                    "symbol": symbol,
                    "name": name,
                    "stance": stance,
                    "summary": ticker_summary,
                    "adminNote": admin_note,
                    "commentary": commentary,
                    "price": live_item.get("price"),
                    "change": live_item.get("change"),
                    "changePercent": live_item.get("changePercent"),
                    "currency": live_item.get("currency"),
                    "sessionLabel": live_item.get("sessionLabel"),
                    "refreshedAt": live_item.get("refreshedAt"),
                    "news": self._normalize_news(live_item.get("news")),
                }
            )
            tickers.append(ticker_payload)

        return tickers

    def _fetch_watchlist_items(self) -> List[Dict[str, Any]]:
        endpoint = self._resolve_watchlist_endpoint()
        if not endpoint:
            return []

        payload = self._fetch_public_json(endpoint)
        if not isinstance(payload, dict):
            return []

        items = payload.get("items") or []
        normalized: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            normalized.append(
                {
                    "symbol": symbol,
                    "name": self._clean_text(str(item.get("name") or "")) or None,
                    "stance": self._clean_text(str(item.get("stance") or "")) or None,
                    "summary": self._clean_text(str(item.get("summary") or "")) or None,
                }
            )
        return normalized

    def _fetch_watchlist_live_items(self) -> List[Dict[str, Any]]:
        endpoint = self._resolve_watchlist_live_endpoint()
        if not endpoint:
            return []

        payload = self._fetch_public_json(endpoint)
        if not isinstance(payload, dict):
            return []

        items = payload.get("items") or []
        return [item for item in items if isinstance(item, dict) and item.get("symbol")]

    def _fetch_public_json(self, endpoint: str) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(endpoint, headers=self.PUBLIC_HEADERS, timeout=10)
        except requests.RequestException as exc:
            logger.info("J2W public fetch skipped: %s", exc)
            return None

        if not (200 <= response.status_code < 300):
            logger.info("J2W public fetch skipped: status=%s endpoint=%s", response.status_code, endpoint)
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.info("J2W public fetch skipped: invalid JSON endpoint=%s", endpoint)
            return None

        return payload if isinstance(payload, dict) else None

    def _resolve_watchlist_endpoint(self) -> Optional[str]:
        return (
            getattr(self.config, "j2w_market_watchlist_endpoint", None)
            or self._derive_related_endpoint(self.DEFAULT_WATCHLIST_PATH)
        )

    def _resolve_watchlist_live_endpoint(self) -> Optional[str]:
        return (
            getattr(self.config, "j2w_market_watchlist_live_endpoint", None)
            or self._derive_related_endpoint(self.DEFAULT_WATCHLIST_LIVE_PATH)
        )

    def _derive_related_endpoint(self, path: str) -> Optional[str]:
        ingest_endpoint = getattr(self.config, "j2w_market_analysis_endpoint", None)
        if not ingest_endpoint:
            return None

        parts = urlsplit(ingest_endpoint)
        if not parts.scheme or not parts.netloc:
            return None

        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))

    def _infer_market_tone(self, summary: str, highlights: List[str]) -> str:
        combined = f"{summary} {' '.join(highlights)}".lower()
        if any(token in combined for token in self._CAUTION_TOKENS):
            return "cautious"
        if any(token in combined for token in self._CONSTRUCTIVE_TOKENS):
            return "constructive"
        return "neutral"

    def _extract_ticker_context(self, markdown_text: str, symbol: str, name: Optional[str]) -> Optional[str]:
        search_terms = [symbol.lower()]
        if name:
            lowered_name = name.lower()
            if lowered_name not in search_terms:
                search_terms.append(lowered_name)

        matches: List[str] = []
        for line in markdown_text.splitlines():
            cleaned = self._clean_text(re.sub(r"^[-*+]\s+", "", line.strip()))
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if any(term and term in lowered for term in search_terms):
                if cleaned not in matches:
                    matches.append(cleaned)
            if len(matches) >= 2:
                break

        if not matches:
            return None

        context = " ".join(matches)
        return context[:280].strip()

    def _build_summary_fallback(self, symbol: str, market_tone: str) -> str:
        if market_tone == "cautious":
            return f"{symbol}는 변동성 확대 구간이라 지지 확인이 우선입니다."
        if market_tone == "constructive":
            return f"{symbol}는 흐름 확인 후 눌림 구간 대응이 유리합니다."
        return f"{symbol}는 방향 확인 전까지 관찰 우선 구간입니다."

    def _build_watchlist_commentary(
        self,
        *,
        symbol: str,
        stance: Optional[str],
        market_tone: str,
        report_context: Optional[str],
    ) -> str:
        if report_context:
            return report_context

        normalized_stance = (stance or "중립").strip()
        if market_tone == "cautious":
            templates = {
                "관심": f"{symbol}는 시장 변동성이 큰 날이라 추격보다 지지 확인이 우선입니다.",
                "경계": f"{symbol}는 단기 리스크 관리 우선 구간으로 보고 무리한 비중 확대를 피하는 편이 좋습니다.",
                "중립": f"{symbol}는 방향 확인 전까지 중립 관찰이 적절합니다.",
            }
        elif market_tone == "constructive":
            templates = {
                "관심": f"{symbol}는 흐름이 살아 있지만 장대 양봉 추격보다 눌림 확인이 유리합니다.",
                "경계": f"{symbol}는 반등이 나와도 과열 확인 전까지 보수적으로 보는 편이 좋습니다.",
                "중립": f"{symbol}는 강세 흐름 속에서도 진입 타이밍 선별이 필요한 구간입니다.",
            }
        else:
            templates = {
                "관심": f"{symbol}는 방향성이 뚜렷해질 때까지 분할 관찰이 적절합니다.",
                "경계": f"{symbol}는 신호가 정리되기 전까지 경계 스탠스를 유지하는 편이 좋습니다.",
                "중립": f"{symbol}는 뚜렷한 우위 신호가 나올 때까지 관찰 우선이 적절합니다.",
            }
        return templates.get(normalized_stance, templates["중립"])

    def _normalize_news(self, news_items: Any) -> List[Dict[str, Any]]:
        if not isinstance(news_items, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for item in news_items[:2]:
            if not isinstance(item, dict):
                continue
            title = self._clean_text(str(item.get("title") or ""))
            url = self._clean_text(str(item.get("url") or ""))
            if not title or not url:
                continue
            normalized.append(
                self._strip_empty_fields(
                    {
                        "title": title,
                        "url": url,
                        "source": self._clean_text(str(item.get("source") or "")) or None,
                        "publishedAt": self._clean_text(str(item.get("publishedAt") or "")) or None,
                    }
                )
            )
        return normalized

    def _strip_empty_fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, list) and not value:
                continue
            cleaned[key] = value
        return cleaned

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
