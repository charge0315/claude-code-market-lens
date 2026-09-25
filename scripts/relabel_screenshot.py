"""note掲載用スクリーンショットのラベル差し替え（2026-09-25 金商法対応、ユーザー指示）.

アプリ画面は CLAUDE.md の規約どおり「推奨買値／推奨損切値／推奨売値」を表示し続けるが、
note記事では「アルゴリズム検証ログ」の語彙（シミュレーション起点価格・シナリオ無効化水準・
想定レンジ上限）に揃える。以前は3値の数値そのものを塗りつぶしていたが、数値は公開する方針に
変わったため、塗りつぶすのはNGラベルの領域だけにし、その上へ新しい用語を描き直す。

矩形の座標はビューポート・スクロール位置で毎回ずれるため、撮影ごとに目視で決めて渡す。

使い方:
    .venv/Scripts/python.exe scripts/relabel_screenshot.py raw.jpg out_relabeled.jpg \
        --box 120,340,210,362=推奨買値 --box 120,370,210,392=推奨損切値

`=` の右側には画面上の元ラベル（NG表現）を書けば、置換後の用語は
`backend/services/notes/compliance_terms.py` の置換表から自動で決まる（用語の単一情報源）。
置換表に無い語を渡した場合は、その文字列をそのまま描く。
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.services.notes.compliance_terms import STOP_TERM, apply_compliance_terms  # noqa: E402

# 画面上の単独ラベルとして現れるが、本文の機械置換対象にすると「損切りすべき」等の文を壊すため
# 置換表（compliance_terms）には入れていない語。ラベル差し替えに限って個別に対応づける。
_UI_LABEL_OVERRIDES = {"損切り": STOP_TERM, "損切": STOP_TERM}

# アプリのサーフェス色（tokens.css の #f5ead8）と本文色に合わせ、差し替え跡を目立たせない。
_DEFAULT_FILL = "#f5ead8"
_DEFAULT_TEXT = "#201e1d"
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]
# 置換後の用語は元ラベルより長いことが多いため、矩形に収まるまでフォントを縮める下限。
_MIN_FONT_SIZE = 8


def _parse_box(spec: str) -> tuple[tuple[int, int, int, int], str]:
    coords, _, label = spec.partition("=")
    parts = [int(v) for v in coords.split(",")]
    if len(parts) != 4 or not label:
        raise argparse.ArgumentTypeError(f"--box は x0,y0,x1,y1=元ラベル の形式で指定してください: {spec}")
    x0, y0, x1, y1 = parts
    if x1 <= x0 or y1 <= y0:
        raise argparse.ArgumentTypeError(f"矩形の座標が不正です（x1>x0, y1>y0 が必要）: {spec}")
    return (x0, y0, x1, y1), label


def _fitting_font(text: str, box: tuple[int, int, int, int]) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    width, height = box[2] - box[0], box[3] - box[1]
    path = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), None)
    if path is None:
        return ImageFont.load_default()
    size = max(_MIN_FONT_SIZE, int(height * 0.8))
    while size > _MIN_FONT_SIZE:
        font = ImageFont.truetype(path, size)
        if font.getlength(text) <= width:
            return font
        size -= 1
    return ImageFont.truetype(path, _MIN_FONT_SIZE)


def relabel(src: str, dst: str, boxes: list[tuple[tuple[int, int, int, int], str]], fill: str, color: str) -> None:
    """各矩形を不透明に塗り、置換後の検証用語を左寄せ・縦中央で描き直す."""
    image = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(image)
    for box, original in boxes:
        label = _UI_LABEL_OVERRIDES.get(original, apply_compliance_terms(original))
        draw.rectangle(box, fill=fill)
        font = _fitting_font(label, box)
        draw.text((box[0], (box[1] + box[3]) / 2), label, font=font, fill=color, anchor="lm")
    image.save(dst, quality=95)


def main() -> None:
    parser = argparse.ArgumentParser(description="スクリーンショットのNGラベルを検証用語へ差し替える")
    parser.add_argument("src", help="元のスクリーンショット")
    parser.add_argument("dst", help="出力先（例: 01_dashboard_shortterm_relabeled.jpg）")
    parser.add_argument("--box", action="append", type=_parse_box, required=True, help="x0,y0,x1,y1=元ラベル")
    parser.add_argument("--fill", default=_DEFAULT_FILL, help="塗りつぶし色")
    parser.add_argument("--color", default=_DEFAULT_TEXT, help="文字色")
    args = parser.parse_args()
    relabel(args.src, args.dst, args.box, args.fill, args.color)
    print(f"[OK] ラベルを差し替えました: {args.dst}")  # noqa: T201 — CLI の完了通知


if __name__ == "__main__":
    main()
