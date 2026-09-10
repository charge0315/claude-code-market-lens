"""J-Quants クライアントの検証（Market Lens から移植）.

外部 API は叩かず、``_get``（トランスポート層）をモックして
リトライ・ページネーション・スキーマガード・DataFrame 整形を確認する。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.services.circuit_breaker import CircuitBreaker
from backend.services.data import jquants_client as jq
from backend.services.data.jquants_client import JQuantsClient
from backend.services.data.jquants_errors import (
    JQuantsCircuitOpenError,
    JQuantsResponseError,
    JQuantsServerError,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[JQuantsClient]:
    """シングルトンを都度リセットし、リトライ待ちを無効化した新しいクライアントを渡す."""
    JQuantsClient._instance = None
    JQuantsClient._ready = False
    c = JQuantsClient()
    c._breaker = CircuitBreaker(failure_threshold=1, cooldown_sec=60.0, open_error_factory=JQuantsCircuitOpenError)

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(jq.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(jq, "_compute_backoff", lambda *_a, **_k: 0.0)
    yield c
    JQuantsClient._instance = None
    JQuantsClient._ready = False


def test_to_5digit_and_date_range() -> None:
    assert JQuantsClient._to_5digit("7203") == "72030"
    assert JQuantsClient._to_5digit("7203.T") == "72030"
    assert JQuantsClient._to_5digit("25935") == "25935"
    frm, to = JQuantsClient._to_date_range("1mo")
    assert frm < to


def test_is_configured_reflects_api_key(client: JQuantsClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jq, "settings", jq.settings.model_copy(update={"jquants_api_key": ""}))
    assert client.is_configured is False
    monkeypatch.setattr(jq, "settings", jq.settings.model_copy(update={"jquants_api_key": "k"}))
    assert client.is_configured is True


async def test_fetch_daily_quotes_builds_ohlcv_frame(client: JQuantsClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: dict[str, object] = {
        "data": [
            {"Date": "2026-09-09", "AdjO": "100", "AdjH": "105", "AdjL": "99", "AdjC": "104", "AdjVo": "1000"},
            {"Date": "2026-09-10", "AdjO": "104", "AdjH": "108", "AdjL": "103", "AdjC": "107", "AdjVo": "1200"},
        ]
    }

    async def fake_get(_endpoint: str, _params: object = None) -> dict[str, object]:
        return payload

    monkeypatch.setattr(client, "_get", fake_get)
    df = await client.fetch_daily_quotes("7203", period="1mo")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 2
    assert df["Close"].iloc[-1] == 107.0


async def test_fetch_daily_quotes_raises_on_all_close_missing(
    client: JQuantsClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get(_endpoint: str, _params: object = None) -> dict[str, object]:
        return {"data": [{"Date": "2026-09-10", "AdjO": "1"}]}  # AdjC 欠落

    monkeypatch.setattr(client, "_get", fake_get)
    with pytest.raises(JQuantsResponseError, match="schema change"):
        await client.fetch_daily_quotes("7203")


async def test_pagination_follows_key(client: JQuantsClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pages: list[dict[str, object]] = [
        {"data": [{"Code": "1"}], "pagination_key": "p2"},
        {"data": [{"Code": "2"}]},
    ]
    calls: list[object] = []

    async def fake_get(_endpoint: str, params: object = None) -> dict[str, object]:
        calls.append(params)
        return pages[len(calls) - 1]

    monkeypatch.setattr(client, "_get", fake_get)
    rows = await client._get_paginated("/equities/master")
    assert [r["Code"] for r in rows] == ["1", "2"]
    second_params = calls[1]
    assert isinstance(second_params, dict)
    assert second_params.get("pagination_key") == "p2"


async def test_retries_server_error_then_opens_circuit(client: JQuantsClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def always_500(_endpoint: str, _params: object = None) -> dict[str, object]:
        raise JQuantsServerError("/x", 503, retry_after="0")

    monkeypatch.setattr(client, "_get", always_500)
    with pytest.raises(JQuantsServerError):
        await client._request_with_retry("/x", None)
    # リトライ枯渇でブレーカ（threshold=1）が OPEN → 次は fast-fail。
    with pytest.raises(JQuantsCircuitOpenError):
        await client._request_with_retry("/x", None)


async def test_check_connection_reports_not_configured(client: JQuantsClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jq, "settings", jq.settings.model_copy(update={"jquants_api_key": ""}))
    result = await client.check_connection()
    assert result["status"] == "not_configured"
