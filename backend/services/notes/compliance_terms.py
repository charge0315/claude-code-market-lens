"""note記事の適法化文言（🆕 2026-09-25 ユーザー指示: 金商法の投資助言・代理業規制対応）.

記事を「読者への売買推奨」ではなく「開発中アルゴリズムの検証ログ・機械的シミュレーション値の
客観的出力」として書くため、NG表現→中立表現の置換表と、記事末尾へ必ず差し込む免責ブロックを
単一情報源としてここに置く（プロンプト・フォーマッタ・図表スクリプトが同じ語彙を使うため）。

LLMの出力は完全には制御できないので、プロンプトで指示するだけでなく生成後にも機械置換する。
ただし「買い」「売り」「カット」単体は「買い物」「売上」「カットオフ」等の一般語を壊すため
機械置換の対象にせず、方向性ラベル（`DIRECTION_LABELS`）とプロンプト指示で担保する。
"""

from __future__ import annotations

__all__ = [
    "COMPLIANCE_DISCLAIMER",
    "DIRECTION_LABELS",
    "TERM_REPLACEMENTS",
    "apply_compliance_terms",
    "find_ng_terms",
    "prompt_rules",
]

ENTRY_TERM = "シミュレーション起点価格"
TARGET_TERM = "想定レンジ上限"
STOP_TERM = "シナリオ無効化水準"

# (NG表現, 置換後)。長い語を先に置換しないと「推奨損切値」が部分一致で崩れるため、
# 適用時に NG 表現の長さ降順へ並べ替える（ここでの並びは可読性優先）。
TERM_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("推奨買値", ENTRY_TERM),
    ("目安買値", ENTRY_TERM),
    ("買い目安", "基準観測値"),
    ("エントリー目安", "基準観測値"),
    ("目標株価", "統計的変動上限（ATR基準）"),
    ("利確ライン", TARGET_TERM),
    ("利確目標", TARGET_TERM),
    ("目標利確", TARGET_TERM),
    ("推奨売値", TARGET_TERM),
    ("損切りライン", STOP_TERM),
    ("損切ライン", STOP_TERM),
    ("推奨損切り価格", STOP_TERM),
    ("推奨損切値", STOP_TERM),
    ("損切値", STOP_TERM),
    ("防衛ライン", "検証撤退閾値"),
    ("ロスカット", "検証撤退閾値"),
    ("推奨銘柄", "アルゴリズム抽出銘柄"),
    ("ピック銘柄", "検証対象銘柄"),
    ("買い推奨", "正のトレンド相関（検証用）"),
    ("売り推奨", "負のトレンド相関（検証用）"),
    ("買いシグナル", "正のトレンド相関シグナル（検証用）"),
    ("売りシグナル", "負のトレンド相関シグナル（検証用）"),
)

_ORDERED_REPLACEMENTS = sorted(TERM_REPLACEMENTS, key=lambda pair: len(pair[0]), reverse=True)

DIRECTION_LABELS: dict[str, str] = {
    "bullish": "正のトレンド相関（検証用）",
    "bearish": "負のトレンド相関（検証用）",
    "neutral": "中立",
}

COMPLIANCE_DISCLAIMER = (
    "---\n"
    "### ⚠️ 【システム検証記録に関する免責事項・注意事項】\n"
    "本記事は、独自開発アルゴリズム「ALPHA FORGE」の動作検証およびデータ分析過程を公開する"
    "技術・運用の個人的な記録ログです。\n"
    "掲載されているすべてのデータ（各スコア、基準観測値、統計的変動上限、シナリオ無効化水準など）は、"
    "過去の市場データに基づき数式（ATR等）により機械的に算出されたバックテスト・シミュレーション用の"
    "パラメータであり、特定の有価証券の売買勧誘、取引の推奨、投資助言・代理行為を目的としたものでは"
    "ありません。\n"
    "また、将来の株価変動や運用成果を保証するものではありません。実際の投資判断および最終決定は、"
    "必ずご自身の責任と判断において行っていただけますようお願いいたします。\n"
    "---"
)


def apply_compliance_terms(text: str) -> str:
    """NG表現を中立的な検証用語へ機械置換する（一般語を壊さないよう複合語のみ対象）."""
    result = text
    for ng, ok in _ORDERED_REPLACEMENTS:
        result = result.replace(ng, ok)
    return result


def find_ng_terms(text: str) -> list[str]:
    """本文に残っている置換対象のNG表現を出現順に返す（テスト・レビュー用）."""
    hits = [(text.find(ng), ng) for ng, _ in TERM_REPLACEMENTS if ng in text]
    return [ng for _, ng in sorted(hits)]


def prompt_rules() -> str:
    """LLMプロンプトへ差し込む用語規則（置換表と同じ語彙を使わせる）."""
    pairs = "\n".join(f"- 「{ng}」→「{ok}」" for ng, ok in TERM_REPLACEMENTS)
    return (
        "【用語規則（厳守）】本記事は開発中アルゴリズムの検証ログであり、読者への売買推奨ではない。"
        "次のNG表現は使わず、右側の検証用語に置き換えること。\n"
        f"{pairs}\n"
        "- 方向性は「買い」「売り」「強気」「弱気」ではなく、「正のトレンド相関（検証用）」"
        "「負のトレンド相関（検証用）」「中立」と書くこと\n"
        "- 「買うべき」「売るべき」「仕込み」等、読者の売買行動を促す表現は使わないこと"
    )
