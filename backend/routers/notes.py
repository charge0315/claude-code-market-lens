"""日次noteドラフト API（🆕）.

`plans/03_システム設計` 相当（AIピック分析結果をもとに、有料note記事の下書きを自動生成し、
人間が確認・編集・承認してから note.com へ手動投稿する半自動フロー）。投稿そのものを行う
エンドポイントは無い（note.comに公式投稿APIが無いため）— `mark-published` は人間が投稿を
終えた後の記録専用。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.models.common import ApiResponse
from backend.models.note import DailyNote, NoteExportResult, NoteMarkPublishedRequest, NoteUpdateRequest
from backend.services.notes import note_service
from backend.services.notes.note_export import export_note_files

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("/today", response_model=ApiResponse[DailyNote | None], summary="本日のnoteドラフト取得")
async def get_today() -> ApiResponse[DailyNote | None]:
    """本日分のドラフトを返す（beatタスクがまだ走っていなければ None）."""
    return ApiResponse.ok(await note_service.get_today())


@router.get("", response_model=ApiResponse[list[DailyNote]], summary="noteドラフト一覧（直近）")
async def list_recent(limit: int = 30) -> ApiResponse[list[DailyNote]]:
    """直近 N 件を新しい順で返す."""
    return ApiResponse.ok(await note_service.list_recent(limit=limit))


@router.post("/generate", response_model=ApiResponse[DailyNote], summary="本日分のドラフトを手動生成")
async def generate(force: bool = False) -> ApiResponse[DailyNote]:
    """本日分を生成する（既にあれば再利用、`force=True` で再生成）."""
    return ApiResponse.ok(await note_service.generate_today(force=force))


@router.patch("/{note_id}", response_model=ApiResponse[DailyNote], summary="ドラフト本文を編集")
async def update(note_id: str, req: NoteUpdateRequest) -> ApiResponse[DailyNote]:
    """タイトル・本文を上書きする（人間のレビュー編集）."""
    note = await note_service.update_content(note_id, title=req.title, body_markdown=req.body_markdown)
    if note is None:
        raise HTTPException(status_code=404, detail="該当するドラフトが見つかりません")
    return ApiResponse.ok(note)


@router.post("/{note_id}/approve", response_model=ApiResponse[DailyNote], summary="ドラフトを承認")
async def approve(note_id: str) -> ApiResponse[DailyNote]:
    """承認する（note.comへの投稿はこの後、人間が手動で行う）."""
    note = await note_service.approve(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="該当するドラフトが見つかりません")
    return ApiResponse.ok(note)


@router.post("/{note_id}/reject", response_model=ApiResponse[DailyNote], summary="ドラフトを却下")
async def reject(note_id: str) -> ApiResponse[DailyNote]:
    """却下する（この日は配信しない）."""
    note = await note_service.reject(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="該当するドラフトが見つかりません")
    return ApiResponse.ok(note)


@router.post("/{note_id}/regenerate", response_model=ApiResponse[DailyNote], summary="ドラフトを再生成")
async def regenerate(note_id: str) -> ApiResponse[DailyNote]:
    """既存ドラフトと同じ日付で作り直す（承認/投稿記録はリセットされる）."""
    note = await note_service.regenerate(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="該当するドラフトが見つかりません")
    return ApiResponse.ok(note)


@router.post(
    "/{note_id}/export",
    response_model=ApiResponse[NoteExportResult],
    summary="Obsidian(.md)・SingleHTMLへ書き出し",
)
async def export(note_id: str) -> ApiResponse[NoteExportResult]:
    """現在のドラフト内容から Obsidian(.md)・SingleHTML を再生成し、Vaultへ保存する.

    編集・承認後に最新内容を反映させたい場合の手動再エクスポート用（自動生成時にも実行される）。
    """
    note = await note_service.get_by_id(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="該当するドラフトが見つかりません")
    note_dir = await export_note_files(note)
    return ApiResponse.ok(NoteExportResult(note_dir=str(note_dir)))


@router.post("/{note_id}/mark-published", response_model=ApiResponse[DailyNote], summary="投稿完了を記録")
async def mark_published(note_id: str, req: NoteMarkPublishedRequest) -> ApiResponse[DailyNote]:
    """人間が note.com への投稿を終えた後、投稿URLを記録する."""
    note = await note_service.mark_published(note_id, published_url=req.published_url)
    if note is None:
        raise HTTPException(status_code=404, detail="該当するドラフトが見つかりません")
    return ApiResponse.ok(note)
