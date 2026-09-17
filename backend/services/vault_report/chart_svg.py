"""チャートSVG生成（🆕 Vaultアーカイブレポート用）.

`frontend/src/components/notes/NoteChart.tsx` と同じ配色・レイアウト方針を Python 側で
再実装したもの（サーバサイド生成のため canvas/PNG ではなく SVG ファイルをそのまま Vault へ
保存する。ObsidianもブラウザもSVGをそのまま表示できるため、追加の画像変換依存は不要）。
新規の重い依存（matplotlib 等）を避ける（YAGNI）。
"""

from __future__ import annotations

from html import escape

_WIDTH = 560
_HEIGHT = 220
_PAD_TOP = 24
_PAD_RIGHT = 16
_PAD_BOTTOM = 28
_PAD_LEFT = 16

_GAIN_HEX = "#b32424"  # 国内証券基準: 上昇=赤
_LOSS_HEX = "#1f6b3a"  # 下落=緑
_FLAT_HEX = "#6b675f"
_BG_HEX = "#f5ead8"
_TEXT_HEX = "#201e1d"
_MUTED_HEX = "#5c584f"


def _chart_color(values: list[float]) -> str:
    if len(values) < 2:
        return _FLAT_HEX
    delta = values[-1] - values[0]
    if delta > 0:
        return _GAIN_HEX
    if delta < 0:
        return _LOSS_HEX
    return _FLAT_HEX


def render_chart_svg(title: str, series: list[tuple[str, float]]) -> str | None:
    """`series`（(日付, 終値) の古い順リスト）から折れ線チャートSVGを返す（2点未満なら None）."""
    if len(series) < 2:
        return None

    values = [v for _, v in series]
    color = _chart_color(values)
    vmin, vmax = min(values), max(values)
    span = (vmax - vmin) or 1.0
    chart_w = _WIDTH - _PAD_LEFT - _PAD_RIGHT
    chart_h = _HEIGHT - _PAD_TOP - _PAD_BOTTOM

    points = []
    for i, v in enumerate(values):
        x = _PAD_LEFT + (i / (len(values) - 1)) * chart_w
        y = _PAD_TOP + chart_h - ((v - vmin) / span) * chart_h
        points.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(points)

    safe_title = escape(title)
    label = escape(f"{safe_title}の値動きチャート（直近{len(values)}日分、ピック前日まで）")

    return (
        f'<svg width="{_WIDTH}" height="{_HEIGHT}" viewBox="0 0 {_WIDTH} {_HEIGHT}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">'
        f'<rect x="0" y="0" width="{_WIDTH}" height="{_HEIGHT}" fill="{_BG_HEX}" />'
        f'<text x="{_PAD_LEFT}" y="16" font-size="14" fill="{_TEXT_HEX}" font-family="sans-serif">{safe_title}</text>'
        f'<text x="{_WIDTH - _PAD_RIGHT}" y="{_PAD_TOP + 4}" font-size="11" fill="{_MUTED_HEX}" '
        f'text-anchor="end" font-family="sans-serif">{vmax:,.0f}</text>'
        f'<text x="{_WIDTH - _PAD_RIGHT}" y="{_HEIGHT - _PAD_BOTTOM}" font-size="11" fill="{_MUTED_HEX}" '
        f'text-anchor="end" font-family="sans-serif">{vmin:,.0f}</text>'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" />'
        f'<text x="{_PAD_LEFT}" y="{_HEIGHT - 8}" font-size="10" fill="{_MUTED_HEX}" font-family="sans-serif">'
        f"直近{len(values)}日分の終値推移（ピック前日まで、参考情報）</text>"
        f"</svg>"
    )
