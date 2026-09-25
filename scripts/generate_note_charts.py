"""note.com 投稿用図表およびアイキャッチ画像生成スクリプト.

4分析レーダーチャート（マルチレーダーグリッド）、
本日のAIピック一覧サマリーテーブル、
およびスマホ一覧・SNSで目を引くアイキャッチ画像を生成する。

2026-09-25（金商法対応、ユーザー指示）: 画像内の文言も「売買推奨」ではなく「アルゴリズム検証ログ」の
語彙に揃える。方向性は picks.json の旧ラベル（強気/弱気）でも中立ラベルへ変換して描画し、
用語の単一情報源は `backend/services/notes/compliance_terms.py` とする。
"""

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# `python scripts/generate_note_charts.py` 実行時は scripts/ が sys.path 先頭になるため、
# 用語の単一情報源（backend パッケージ）を import できるようリポジトリルートを追加する。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.services.notes.compliance_terms import DIRECTION_LABELS, apply_compliance_terms  # noqa: E402

# picks.json の方向性は旧来の「強気/弱気」や英語キーで書かれていることがあるため中立ラベルへ寄せる。
_LEGACY_DIRECTION_KEYS = {"強気": "bullish", "買い": "bullish", "弱気": "bearish", "売り": "bearish", "中立": "neutral"}


def neutral_direction(direction: str) -> str:
    """方向性を検証用の中立ラベル（正/負のトレンド相関（検証用）/中立）へ変換する."""
    key = _LEGACY_DIRECTION_KEYS.get(direction, direction)
    return DIRECTION_LABELS.get(key, apply_compliance_terms(direction))

# 日本語フォント設定（Windows環境優先）
FONTS = ["Yu Gothic", "Meiryo", "MS Gothic", "TakaoPGothic", "IPAexGothic", "sans-serif"]
matplotlib.rcParams["font.sans-serif"] = FONTS
matplotlib.rcParams["axes.unicode_minus"] = False


def get_japanese_font() -> FontProperties:
    """利用可能な日本語フォントプロパティを取得する."""
    for font_name in ["Yu Gothic", "Meiryo", "MS Gothic"]:
        try:
            return FontProperties(family=font_name)
        except Exception:
            continue
    return FontProperties(family="sans-serif")


def get_pil_japanese_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """PIL用の日本語フォントを取得する."""
    font_paths = [
        ("C:/Windows/Fonts/meiryob.ttc" if bold else "C:/Windows/Fonts/meiryo.ttc"),
        ("C:/Windows/Fonts/YuGothB.ttc" if bold else "C:/Windows/Fonts/YuGothM.ttc"),
        ("C:/Windows/Fonts/BIZ-UDGothicB.ttc" if bold else "C:/Windows/Fonts/BIZ-UDGothicR.ttc"),
        "C:/Windows/Fonts/msgothic.ttc",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_radar_charts(
    picks_data: List[Dict[str, Any]],
    output_path: str,
    title: str = "本日のアルゴリズム抽出銘柄 4分析レーダー比較",
) -> None:
    """各銘柄の4分析スコアをマルチレーダーチャート（2〜3列グリッド）として描画する."""
    n_picks = len(picks_data)
    if n_picks == 0:
        return

    cols = 3 if n_picks >= 3 else n_picks
    rows = math.ceil(n_picks / cols)

    fig, axes = plt.subplots(
        rows,
        cols,
        figsize=(cols * 4.6, rows * 4.4),
        subplot_kw=dict(polar=True),
        facecolor="#fcfaf7",
    )

    if n_picks == 1:
        axes_list = [axes]
    elif rows == 1:
        axes_list = list(axes)
    else:
        axes_list = axes.flatten().tolist()

    categories = ["テクニカル", "トレンド", "ファンダ", "センチメント"]
    N = len(categories)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]

    palette = ["#c67139", "#335c67", "#7a8a5e", "#9e2a2b", "#d4813f", "#3d5a80"]
    font_jp = get_japanese_font()

    for idx, pick in enumerate(picks_data):
        ax = axes_list[idx]
        ax.set_facecolor("#ffffff")
        scores_dict = pick.get("scores", {})
        values = [
            scores_dict.get("テクニカル", 50),
            scores_dict.get("トレンド", 50),
            scores_dict.get("ファンダ", 50),
            scores_dict.get("センチメント", 50),
        ]
        values += values[:1]

        color = palette[idx % len(palette)]

        ax.plot(angles, values, color=color, linewidth=2.5, linestyle="solid")
        ax.fill(angles, values, color=color, alpha=0.3)

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontproperties=font_jp, fontsize=12, fontweight="bold", color="#2b2520")

        ax.set_rlabel_position(0)
        ax.set_yticks([25, 50, 75, 100])
        ax.set_yticklabels(["25", "50", "75", "100"], fontsize=9, color="#8c827a")
        ax.set_ylim(0, 100)
        ax.grid(color="#ded4c8", linestyle="--", linewidth=0.8)

        label_text = f"【{pick.get('symbol', '')}】{pick.get('name', '')}\n({pick.get('horizon', '')}・{neutral_direction(str(pick.get('direction', '')))})"
        ax.set_title(
            label_text,
            fontproperties=font_jp,
            fontsize=13,
            fontweight="bold",
            color="#20160e",
            pad=20,
        )

    for idx in range(n_picks, len(axes_list)):
        axes_list[idx].set_visible(False)

    plt.suptitle(
        title,
        fontproperties=font_jp,
        fontsize=16,
        fontweight="bold",
        color="#20160e",
        y=1.02,
    )

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"[OK] レーダーチャートを保存しました: {output_path}")


def draw_pick_table(
    table_data: List[Dict[str, Any]],
    output_path: str,
    title: str = "本日のアルゴリズム抽出銘柄 サマリー一覧",
    footnote: str = (
        "※アルゴリズムの動作検証記録です。方向性・スコアは過去データから機械的に算出した値であり、"
        "売買の推奨ではありません。"
    ),
) -> None:
    """サマリーテーブルをスマホでも読みやすい大フォント画像として描画する."""
    font_jp = get_japanese_font()

    columns = ["区分", "銘柄コード", "銘柄名", "方向性（検証用）", "合成スコア", "審査員一致度", "確度"]
    cell_data = []

    for row in table_data:
        cell_data.append([
            row.get("horizon", "中長期"),
            row.get("symbol", "-"),
            row.get("name", "-"),
            neutral_direction(str(row.get("direction", "中立"))),
            f"{row.get('composite_score', 0):.1f}",
            f"{row.get('concordance', 0):.2f}",
            f"{row.get('confidence', 0)}%",
        ])

    rows_count = len(cell_data)
    fig_height = max(3.5, 1.2 + rows_count * 0.6)
    fig, ax = plt.subplots(figsize=(10.5, fig_height), facecolor="#fcfaf7")
    ax.axis("off")

    table = ax.table(
        cellText=cell_data,
        colLabels=columns,
        # 中立ラベル「正のトレンド相関（検証用）」は旧「強気」より長いため方向性列を広く取る。
        colWidths=[0.08, 0.1, 0.19, 0.27, 0.12, 0.13, 0.11],
        loc="center",
        cellLoc="center",
    )

    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1.0, 1.8)

    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#dfd5c8")
        cell.set_linewidth(1.0)
        if r == 0:
            cell.set_facecolor("#c67139")
            cell.get_text().set_color("#ffffff")
            cell.get_text().set_fontproperties(font_jp)
            cell.get_text().set_fontweight("bold")
            cell.get_text().set_fontsize(12)
        else:
            cell.get_text().set_fontproperties(font_jp)
            cell.get_text().set_color("#20160e")
            if r % 2 == 1:
                cell.set_facecolor("#ffffff")
            else:
                cell.set_facecolor("#f7efe6")

    plt.title(
        title,
        fontproperties=font_jp,
        fontsize=15,
        fontweight="bold",
        color="#20160e",
        pad=18,
    )

    plt.figtext(
        0.5,
        0.02,
        footnote,
        fontproperties=font_jp,
        fontsize=10,
        color="#70655e",
        ha="center",
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"[OK] サマリーテーブルを保存しました: {output_path}")


def draw_cover_image(
    date_str: str,
    main_title: str,
    tickers_list: List[str],
    output_path: str,
    sub_title: str = "ALPHA FORGE 検証ログ：日本株アルゴリズムの抽出銘柄と思考トレース",
) -> None:
    """note.com推奨比率（1.91:1 / 1280x670）のアイキャッチ画像を生成する."""
    W, H = 1280, 670

    # 1. 背景グリッド
    bg_color = (245, 234, 216)  # #f5ead8
    grid_color = (236, 222, 201)  # #ecdec9
    img = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(img)

    for x in range(0, W, 40):
        draw.line([(x, 0), (x, H)], fill=grid_color, width=1)
    for y in range(0, H, 40):
        draw.line([(0, y), (W, y)], fill=grid_color, width=1)

    # 2. メインカード（白背景の丸角矩形 + シャドウ）
    card_margin_x = 60
    card_margin_y = 50
    card_x1 = card_margin_x
    card_y1 = card_margin_y
    card_x2 = W - card_margin_x
    card_y2 = H - card_margin_y
    radius = 16

    # シャドウ
    shadow_offset = 8
    draw.rounded_rectangle(
        [(card_x1 + shadow_offset, card_y1 + shadow_offset), (card_x2 + shadow_offset, card_y2 + shadow_offset)],
        radius=radius,
        fill=(210, 195, 175),
    )
    # カード本体
    draw.rounded_rectangle([(card_x1, card_y1), (card_x2, card_y2)], radius=radius, fill=(255, 255, 255), outline=(198, 113, 57), width=3)

    # 3. 日付バッジ（左上）
    badge_x = card_x1 + 40
    badge_y = card_y1 + 40
    badge_h = 42
    font_badge = get_pil_japanese_font(20, bold=True)
    badge_text = f"DAILY AI REPORT ｜ {date_str}"
    # 固定幅だと日付が切れるため、文字幅 + 左右パディングからバッジ幅を決める
    text_bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    badge_w = (text_bbox[2] - text_bbox[0]) + 36
    draw.rounded_rectangle([(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)], radius=8, fill=(198, 113, 57))
    draw.text((badge_x + 18, badge_y + 8), badge_text, fill=(255, 255, 255), font=font_badge)

    # 4. サブタイトル
    font_sub = get_pil_japanese_font(22, bold=False)
    draw.text((badge_x, badge_y + 60), sub_title, fill=(110, 100, 90), font=font_sub)

    # 5. メインタイトル（大きく表示、長ければ改行）
    font_title = get_pil_japanese_font(44, bold=True)
    title_y = badge_y + 115

    # タイトルの簡易自動折り返し（全角20文字程度で分割）
    max_chars = 18
    lines = []
    if len(main_title) <= max_chars:
        lines = [main_title]
    else:
        # 句読点やスペース、助詞を意識して分割
        lines.append(main_title[:max_chars])
        lines.append(main_title[max_chars:])

    for i, line in enumerate(lines[:2]):
        draw.text((badge_x, title_y + (i * 62)), line, fill=(32, 22, 14), font=font_title)

    # 6. ピック銘柄タグ（下部に並べる）
    tag_start_y = card_y2 - 95
    font_tag = get_pil_japanese_font(20, bold=True)

    draw.text((badge_x, tag_start_y - 30), "■ 本日の検証対象銘柄:", fill=(140, 120, 105), font=get_pil_japanese_font(18, bold=True))

    curr_x = badge_x
    for ticker in tickers_list[:5]:
        text_bbox = draw.textbbox((0, 0), ticker, font=font_tag)
        tag_w = (text_bbox[2] - text_bbox[0]) + 30
        tag_h = 42
        draw.rounded_rectangle([(curr_x, tag_start_y), (curr_x + tag_w, tag_start_y + tag_h)], radius=6, fill=(247, 239, 230), outline=(210, 185, 160), width=1)
        draw.text((curr_x + 15, tag_start_y + 8), ticker, fill=(198, 113, 57), font=font_tag)
        curr_x += tag_w + 14

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, quality=95)
    print(f"[OK] カバー画像を保存しました: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="note.com用図表生成ツール")
    parser.add_argument("--json-file", help="ピック情報のJSONファイルパス")
    parser.add_argument("--output-dir", default="docs/note/sample/images", help="画像出力先ディレクトリ")
    parser.add_argument("--date", default="2026-09-23", help="日付文字列（YYYY-MM-DD）")
    parser.add_argument("--title", default="AIが読む半導体相場と国内6銘柄への波及シナリオ", help="メインタイトル")
    parser.add_argument("--sub-title", default=None, help="サブタイトル（省略時はデフォルト）")
    parser.add_argument("--tags", nargs="*", default=None, help="カバー画像下部に表示するタグ（空白区切り複数指定可）")
    parser.add_argument("--skip-charts", action="store_true", help="チャート・表の生成をスキップしカバーのみ生成")
    args = parser.parse_args()

    sample_picks = [
        {
            "symbol": "285A",
            "name": "キオクシアHD",
            "horizon": "中長期",
            "direction": "強気",
            "composite_score": 64.2,
            "concordance": 0.33,
            "confidence": 45,
            "scores": {"テクニカル": 85, "トレンド": 20, "ファンダ": 40, "センチメント": 75},
        },
        {
            "symbol": "4047",
            "name": "関東電化工業",
            "horizon": "中長期",
            "direction": "強気",
            "composite_score": 58.1,
            "concordance": 0.50,
            "confidence": 42,
            "scores": {"テクニカル": 65, "トレンド": 60, "ファンダ": 55, "センチメント": 50},
        },
        {
            "symbol": "9984",
            "name": "ソフトバンクG",
            "horizon": "短期",
            "direction": "強気",
            "composite_score": 55.7,
            "concordance": 0.33,
            "confidence": 42,
            "scores": {"テクニカル": 52, "トレンド": 48, "ファンダ": 80, "センチメント": 35},
        },
        {
            "symbol": "8001",
            "name": "伊藤忠商事",
            "horizon": "短期",
            "direction": "強気",
            "composite_score": 54.0,
            "concordance": 0.50,
            "confidence": 40,
            "scores": {"テクニカル": 42, "トレンド": 90, "ファンダ": 68, "センチメント": 52},
        },
        {
            "symbol": "1360",
            "name": "日経ベア2倍",
            "horizon": "短期",
            "direction": "強気",
            "composite_score": 57.6,
            "concordance": 0.50,
            "confidence": 41,
            "scores": {"テクニカル": 68, "トレンド": 55, "ファンダ": 45, "センチメント": 50},
        },
    ]

    picks = sample_picks
    if args.json_file and os.path.exists(args.json_file):
        with open(args.json_file, "r", encoding="utf-8") as f:
            picks = json.load(f)

    radar_out = os.path.join(args.output_dir, "07_radar_chart.png")
    table_out = os.path.join(args.output_dir, "06_pick_summary_table.png")
    cover_out = os.path.join(args.output_dir, f"00_cover_{args.date}.png")

    tickers = args.tags if args.tags else [f"{p.get('symbol')} {p.get('name')}" for p in picks]
    sub_title = args.sub_title if args.sub_title else "ALPHA FORGE 検証ログ：日本株アルゴリズムの抽出銘柄と思考トレース"

    if not args.skip_charts:
        draw_radar_charts(picks, radar_out)
        draw_pick_table(picks, table_out)

    draw_cover_image(args.date, args.title, tickers, cover_out, sub_title=sub_title)


if __name__ == "__main__":
    main()
