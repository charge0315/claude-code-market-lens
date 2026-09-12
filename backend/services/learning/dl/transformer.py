"""Transformer による株価予測サービス（銘柄別モデル、P9）.

Market Lens `backend/services/dl/transformer.py` から移植（変更なし）。学習ループ・標準化・
保存/読込などの共通処理は BaseTorchPredictor が担うため、本クラスはネットワーク構造の
構築（_build_network）とアーキテクチャパラメータの抽出（_extract_arch_params）のみを実装する。
"""

from __future__ import annotations

from typing import cast

try:
    import torch.nn as nn
except ImportError:  # pragma: no cover
    # from __future__ import annotations により型注釈は文字列として遅延評価されるため、
    # torch 未インストール時に nn を実行時に再代入する必要はない
    pass

from backend.services.learning.dl.base import BaseTorchPredictor
from backend.services.learning.dl.networks import _TransformerNet
from backend.services.learning.predictor_protocol import Hyperparams


class TransformerPredictor(BaseTorchPredictor):
    """Transformer による株価変化率予測モデル."""

    def _build_network(self, arch_params: Hyperparams, input_size: int) -> nn.Module:
        # 呼び出し元（train / load / 旧形式フォールバック）でキーが
        # 揃わないことがあるため .get で防御的に取り出す
        d_model = int(arch_params.get("d_model", 64))
        nhead = int(arch_params.get("nhead", 4))
        if d_model % nhead != 0:
            # nn.MultiheadAttention は d_model を nhead で均等分割できないと
            # 構築できないため、学習開始前にわかりやすいメッセージで弾く
            raise ValueError(f"d_model({d_model})はnhead({nhead})で割り切れる必要があります")
        num_layers = int(arch_params.get("num_layers", 2))
        dim_feedforward = int(arch_params.get("dim_feedforward", d_model * 2))
        dropout = float(arch_params.get("dropout", 0.2))
        return _TransformerNet(
            input_size=input_size,
            d_model=d_model,
            nhead=nhead,
            num_layers=num_layers,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
        )

    def _extract_arch_params(self) -> Hyperparams:
        # メソッドをまたいだ narrowing は mypy が追えないため cast で明示する
        # （lstm.py と同じ理由で assert は使わない）
        model = cast(_TransformerNet, self.model)
        return {
            "d_model": int(model.d_model),
            "nhead": int(model.nhead),
            "num_layers": int(model.num_layers),
            "dim_feedforward": int(model.dim_feedforward),
            # MC Dropout推論では実際のdropout率が必要なため、学習時に指定された
            # 値をそのまま保存する。TransformerEncoderLayer内部のnn.Dropoutはこの値で
            # 構築されており、MC Dropout推論時に確率的ばらつきを生む
            "dropout": float(model.dropout_rate),
        }
