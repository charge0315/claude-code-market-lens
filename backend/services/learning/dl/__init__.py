"""深層学習（PyTorch）予測モデルのパッケージ（銘柄別モデル、P9）.

Market Lens `backend/services/dl/__init__.py` から移植（変更なし）。BaseTorchPredictor が
学習ループ・標準化・保存/読込などの共通基盤を提供し、各モデル（LSTM/Transformer）は
ネットワーク構造だけをサブクラスで差し替える設計。
"""

from __future__ import annotations

from backend.services.learning.dl.lstm import LSTMPredictor
from backend.services.learning.dl.transformer import TransformerPredictor

__all__ = ["LSTMPredictor", "TransformerPredictor"]
