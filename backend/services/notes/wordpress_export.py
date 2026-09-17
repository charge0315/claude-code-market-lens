"""note下書きのWordPress WXR（.xml）書き出し（🆕 ユーザー指示: note.comへの転記に加えて
WordPressへもインポートできる形式で出力する）.

note.comには公式投稿APIが無く常に人間が手動投稿するため（`note_service.py` docstring参照）、
同じ下書きを自前WordPressサイトにも展開できるよう、Obsidian(.md)・SingleHTMLに加えて
WordPress標準のインポート形式（WXR = WordPress eXtended RSS）でも書き出す。
画像添付（`wp:attachment_url`）は実際のホスティング先がまだ無いため、`tables/<ファイル名>`の
相対パスを暫定値として埋め込む — インポート前に到達可能なURLへの差し替えが必要（このアプリは
Vaultへの書き出しまでを担当し、投稿・ホスティングは従来どおり人間が行う半自動フローを踏襲）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime
from html import escape
from pathlib import Path

from backend.models.note import DailyNote
from backend.services.jst_time import JST
from backend.services.notes.markdown_to_html import markdown_to_html

# ユーザー指示の上限（20MB）。表画像はXMLへ埋め込まない（URL参照のみ）ため通常到達しないが、
# 本文が極端に肥大化した場合の書き出し拒否用にサーバ側で検証する（フェイルファスト）。
_MAX_WXR_SIZE_BYTES = 20 * 1024 * 1024

_SITE_TITLE = "ALPHA FORGE"
_SITE_LINK = "https://note.com/"
_CREATOR = "AI Market Analyst"
_TAGS = ["note/stock", "ai-pick", "日本株", "投資戦略"]

# note下書きのstatusはnote.com向けの承認フロー用のため、WordPress側の投稿状態へ読み替える。
_WXR_STATUS_MAP: dict[str, str] = {
    "draft": "draft",
    "approved": "draft",
    "rejected": "draft",
    "published": "publish",
}


def _cdata(text: str) -> str:
    """CDATAセクション終端記号 `]]>` の混入を無害化してラップする."""
    return f"<![CDATA[{text.replace(']]>', ']]]]><![CDATA[>')}]]>"


def _rfc822(dt: datetime) -> str:
    return format_datetime(dt)


def _wp_local(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _slug(note: DailyNote) -> str:
    return f"note-{note.note_date}-{note.note_id}"


def _validate_size(xml: str) -> None:
    size = len(xml.encode("utf-8"))
    if size > _MAX_WXR_SIZE_BYTES:
        raise ValueError(f"WXR出力がユーザー指定の上限（20MB）を超えています: {size / 1024 / 1024:.1f}MB")


def _attachment_item(*, filename: str, post_id: int, parent_id: int, now: datetime) -> str:
    name = Path(filename).stem
    return f"""    <item>
        <title>{escape(filename)}</title>
        <link>{escape(_SITE_LINK)}?attachment_id={post_id}</link>
        <pubDate>{_rfc822(now)}</pubDate>
        <dc:creator>{_cdata(_CREATOR)}</dc:creator>
        <guid isPermaLink="false">urn:alphaforge:attachment:{post_id}</guid>
        <description></description>
        <content:encoded>{_cdata("")}</content:encoded>
        <excerpt:encoded>{_cdata("")}</excerpt:encoded>
        <wp:post_id>{post_id}</wp:post_id>
        <wp:post_date>{_wp_local(now)}</wp:post_date>
        <wp:post_date_gmt>{_wp_local(now.astimezone(UTC))}</wp:post_date_gmt>
        <wp:comment_status>closed</wp:comment_status>
        <wp:ping_status>closed</wp:ping_status>
        <wp:post_name>{escape(name)}</wp:post_name>
        <wp:status>inherit</wp:status>
        <wp:post_parent>{parent_id}</wp:post_parent>
        <wp:menu_order>0</wp:menu_order>
        <wp:post_type>attachment</wp:post_type>
        <wp:post_password></wp:post_password>
        <wp:is_sticky>0</wp:is_sticky>
        <wp:attachment_url>tables/{escape(filename)}</wp:attachment_url>
    </item>
"""


def build_wxr_xml(note: DailyNote, *, table_image_filenames: list[str]) -> str:
    """note下書きをWordPress WXR 1.2形式のXML文字列として組み立てる.

    本文は既存の `markdown_to_html`（SingleHTML書き出しと同じ変換）を再利用し、表画像は
    Obsidian書き出しと同じ `tables/<ファイル名>` 相対パスで `<img>` 参照する（DRY）。
    """
    now = datetime.now(JST)
    post_id = 1

    body_html = markdown_to_html(note.body_markdown)
    if table_image_filenames:
        images_html = "".join(
            f'<p><img src="tables/{escape(f)}" alt="{escape(f)}" /></p>' for f in table_image_filenames
        )
        body_html = f"{body_html}\n{images_html}"

    status = _WXR_STATUS_MAP.get(note.status, "draft")
    tags_xml = "".join(
        f'<category domain="post_tag" nicename="{escape(tag)}">{_cdata(tag)}</category>' for tag in _TAGS
    )
    attachments_xml = "".join(
        _attachment_item(filename=filename, post_id=post_id + i + 1, parent_id=post_id, now=now)
        for i, filename in enumerate(table_image_filenames)
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"
  xmlns:excerpt="http://wordpress.org/export/1.2/excerpt/"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:wfw="http://wellformedweb.org/CommentAPI/"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:wp="http://wordpress.org/export/1.2/"
>
<channel>
    <title>{escape(_SITE_TITLE)}</title>
    <link>{escape(_SITE_LINK)}</link>
    <description>{_cdata("日本株AI銘柄ピック分析note下書き（WordPressインポート用）")}</description>
    <pubDate>{_rfc822(now)}</pubDate>
    <language>ja</language>
    <wp:wxr_version>1.2</wp:wxr_version>
    <wp:base_site_url>{escape(_SITE_LINK)}</wp:base_site_url>
    <wp:base_blog_url>{escape(_SITE_LINK)}</wp:base_blog_url>
    <item>
        <title>{escape(note.title)}</title>
        <link>{escape(_SITE_LINK)}?p={post_id}</link>
        <pubDate>{_rfc822(now)}</pubDate>
        <dc:creator>{_cdata(_CREATOR)}</dc:creator>
        <guid isPermaLink="false">urn:alphaforge:note:{escape(note.note_id)}</guid>
        <description></description>
        <content:encoded>{_cdata(body_html)}</content:encoded>
        <excerpt:encoded>{_cdata("")}</excerpt:encoded>
        <wp:post_id>{post_id}</wp:post_id>
        <wp:post_date>{_wp_local(now)}</wp:post_date>
        <wp:post_date_gmt>{_wp_local(now.astimezone(UTC))}</wp:post_date_gmt>
        <wp:comment_status>closed</wp:comment_status>
        <wp:ping_status>closed</wp:ping_status>
        <wp:post_name>{escape(_slug(note))}</wp:post_name>
        <wp:status>{status}</wp:status>
        <wp:post_parent>0</wp:post_parent>
        <wp:menu_order>0</wp:menu_order>
        <wp:post_type>post</wp:post_type>
        <wp:post_password></wp:post_password>
        <wp:is_sticky>0</wp:is_sticky>
        {tags_xml}
    </item>
{attachments_xml}</channel>
</rss>
"""
    _validate_size(xml)
    return xml
