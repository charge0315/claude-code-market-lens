"""`services/vault_report/vault_writer` の検証（Market Lensと衝突しない専用パスへの書き込み）."""

from __future__ import annotations

from backend.services.vault_report import vault_writer as vw
from backend.tests.conftest import VaultDirs


def test_report_dir_for_date_is_isolated_from_market_lens_daily_notes(vault_dirs: VaultDirs) -> None:
    """`Daily/AlphaForge/<日付>/` はMarket Lensの `Daily/YYYY-MM-DD.md` と衝突しないパスであること."""
    report_dir = vw.report_dir_for_date("2026-09-17")

    assert report_dir == vault_dirs.daily / "AlphaForge" / "2026-09-17"
    # Market Lens が書く実体（Daily/2026-09-17.md）はディレクトリではなくファイルなので、
    # 同名でぶつかる余地が無いことを確認する。
    assert not (vault_dirs.daily / "2026-09-17.md").exists()


def test_write_report_creates_html_and_charts(vault_dirs: VaultDirs) -> None:
    report_dir = vw.write_report(
        "2026-09-17",
        html="<html><body>test</body></html>",
        charts={"7203": "<svg>a</svg>", "9984": "<svg>b</svg>"},
    )

    assert (report_dir / "report.html").read_text(encoding="utf-8") == "<html><body>test</body></html>"
    assert (report_dir / "charts" / "7203.svg").read_text(encoding="utf-8") == "<svg>a</svg>"
    assert (report_dir / "charts" / "9984.svg").read_text(encoding="utf-8") == "<svg>b</svg>"


def test_write_report_overwrites_on_regeneration(vault_dirs: VaultDirs) -> None:
    vw.write_report("2026-09-17", html="<html>old</html>", charts={"7203": "<svg>old</svg>"})

    report_dir = vw.write_report("2026-09-17", html="<html>new</html>", charts={"7203": "<svg>new</svg>"})

    assert (report_dir / "report.html").read_text(encoding="utf-8") == "<html>new</html>"
    assert (report_dir / "charts" / "7203.svg").read_text(encoding="utf-8") == "<svg>new</svg>"
