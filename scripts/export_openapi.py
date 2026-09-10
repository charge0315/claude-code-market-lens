"""OpenAPI スキーマを docs/openapi.json へ書き出す.

使い方:
    .venv/Scripts/python.exe scripts/export_openapi.py

CI（push 前ローカル含む）で実行し、スキーマ差分をレビュー可能にする。
必須 env が無くても import できるようダミー値を先に入れる（本番値とは無関係）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("ML_SECRET_KEY", "dummy-for-openapi-export-32chars!!")
os.environ.setdefault("ML_PASSWORD_HASH", "dummy-hash-for-openapi-export")

from backend.main import app  # noqa: E402

schema = app.openapi()
output = _ROOT / "docs" / "openapi.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Exported {len(schema.get('paths', {}))} paths -> {output}")
