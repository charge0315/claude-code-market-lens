"""note記事の適法化文言（NG表現の機械置換・免責ブロック）のテスト."""

from __future__ import annotations

import pytest

from backend.services.notes import compliance_terms as ct
from backend.services.notes.markdown_to_html import markdown_to_html


@pytest.mark.parametrize(
    ("ng", "ok"),
    [
        ("推奨買値", "シミュレーション起点価格"),
        ("目安買値", "シミュレーション起点価格"),
        ("買い目安", "基準観測値"),
        ("エントリー目安", "基準観測値"),
        ("目標株価", "統計的変動上限（ATR基準）"),
        ("利確ライン", "想定レンジ上限"),
        ("利確目標", "想定レンジ上限"),
        ("目標利確", "想定レンジ上限"),
        ("推奨売値", "想定レンジ上限"),
        ("損切りライン", "シナリオ無効化水準"),
        ("損切ライン", "シナリオ無効化水準"),
        ("推奨損切値", "シナリオ無効化水準"),
        ("防衛ライン", "検証撤退閾値"),
        ("ロスカット", "検証撤退閾値"),
        ("推奨銘柄", "アルゴリズム抽出銘柄"),
        ("ピック銘柄", "検証対象銘柄"),
        ("買い推奨", "正のトレンド相関（検証用）"),
        ("売り推奨", "負のトレンド相関（検証用）"),
    ],
)
def test_apply_compliance_terms_replaces_ng_phrase(ng: str, ok: str) -> None:
    result = ct.apply_compliance_terms(f"本日の{ng}は次の通り")

    assert ok in result
    assert ng not in result


def test_apply_compliance_terms_prefers_longest_match() -> None:
    # 「推奨損切値」を「損切」単体より先に処理しないと「推奨シナリオ無効化水準」のような崩れ方をする。
    result = ct.apply_compliance_terms("推奨損切値と推奨売値")

    assert result == "シナリオ無効化水準と想定レンジ上限"


def test_apply_compliance_terms_leaves_ordinary_words_untouched() -> None:
    # 「買い物」「売上」「カットオフ」等の一般語まで機械置換すると文章が壊れるため対象外。
    text = "売上高が伸び、買い物需要も堅調。データのカットオフは前日終値。"

    assert ct.apply_compliance_terms(text) == text


def test_find_ng_terms_reports_remaining_phrases() -> None:
    assert ct.find_ng_terms("目標株価と防衛ラインを確認") == ["目標株価", "防衛ライン"]
    assert ct.find_ng_terms("検証対象銘柄のスコア") == []


def test_direction_labels_are_neutralized() -> None:
    assert ct.DIRECTION_LABELS == {
        "bullish": "正のトレンド相関（検証用）",
        "bearish": "負のトレンド相関（検証用）",
        "neutral": "中立",
    }


def test_disclaimer_block_is_the_fixed_text() -> None:
    assert "### ⚠️ 【システム検証記録に関する免責事項・注意事項】" in ct.COMPLIANCE_DISCLAIMER
    assert "独自開発アルゴリズム「ALPHA FORGE」" in ct.COMPLIANCE_DISCLAIMER
    assert "投資助言・代理行為を目的としたものではありません" in ct.COMPLIANCE_DISCLAIMER
    # 本文は3項目の箇条書き（2026-09-25 ユーザー指示）。
    bullets = [line for line in ct.COMPLIANCE_DISCLAIMER.splitlines() if line.startswith("- ")]
    assert len(bullets) == 3
    assert bullets[0].startswith("- 本記事は、独自開発アルゴリズム")
    assert bullets[2].startswith("- また、将来の株価変動")
    assert ct.COMPLIANCE_DISCLAIMER.strip().startswith("---")
    # SingleHTML 書き出しで区切り線・見出し・リストがそれぞれ正しいブロックになること。
    html = markdown_to_html(ct.COMPLIANCE_DISCLAIMER)
    assert "---" not in html
    assert "###" not in html
    assert html.count("<hr>") == 2
    assert html.count("<li>") == 3
    assert ct.COMPLIANCE_DISCLAIMER.strip().endswith("---")
    # 定型文に置換対象のNG表現が混ざっていないこと。
    assert ct.find_ng_terms(ct.COMPLIANCE_DISCLAIMER) == []
