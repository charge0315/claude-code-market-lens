"""`services/vault_report/chart_svg` の検証（配色ロジック・XSS対策・データ不足時の挙動）."""

from __future__ import annotations

from backend.services.vault_report.chart_svg import render_chart_svg


def test_render_chart_svg_returns_none_for_insufficient_data() -> None:
    assert render_chart_svg("7203", []) is None
    assert render_chart_svg("7203", [("2026-09-16", 100.0)]) is None


def test_render_chart_svg_uses_gain_color_for_uptrend() -> None:
    svg = render_chart_svg("7203", [("2026-09-15", 100.0), ("2026-09-16", 110.0)])

    assert svg is not None
    assert "#b32424" in svg  # 上昇=赤（国内証券基準）


def test_render_chart_svg_uses_loss_color_for_downtrend() -> None:
    svg = render_chart_svg("7203", [("2026-09-15", 110.0), ("2026-09-16", 100.0)])

    assert svg is not None
    assert "#1f6b3a" in svg  # 下落=緑


def test_render_chart_svg_escapes_title_against_xss() -> None:
    svg = render_chart_svg("<script>alert(1)</script>", [("2026-09-15", 100.0), ("2026-09-16", 110.0)])

    assert svg is not None
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_render_chart_svg_includes_min_max_labels() -> None:
    svg = render_chart_svg("7203", [("2026-09-15", 100.0), ("2026-09-16", 150.0), ("2026-09-17", 120.0)])

    assert svg is not None
    assert "150" in svg
    assert "100" in svg
