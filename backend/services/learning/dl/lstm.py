"""LSTM による株価予測サービス（銘柄別モデル、P9）.

Market Lens `backend/services/dl/lstm.py` から移植（変更なし）。学習ループ・標準化・
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
from backend.services.learning.dl.networks import _LSTMNet
from backend.services.learning.predictor_protocol import Hyperparams


class LSTMPredictor(BaseTorchPredictor):
    """LSTM による株価変化率予測モデル."""

    def _build_network(self, arch_params: Hyperparams, input_size: int) -> nn.Module:
        # 呼び出し元（train / load / 旧形式フォールバック）でキーが
        # 揃わないことがあるため .get で防御的に取り出す
        hidden_size = int(arch_params.get("hidden_size", 64))
        num_layers = int(arch_params.get("num_layers", 2))
        dropout = float(arch_params.get("dropout", 0.2))
        return _LSTMNet(input_size=input_size, hidden_size=hidden_size, num_layers=num_layers, dropout=dropout)

    def _extract_arch_params(self) -> Hyperparams:
        # save() は self.model が None でないことを保証してから本メソッドを呼ぶが、
        # メソッドをまたいだ narrowing は mypy が追えないため cast で明示する
        # （assert は bandit B101 対象かつ -O 最適化で除去されるため使わない）
        model = cast(_LSTMNet, self.model)
        return {
            "hidden_size": int(model.lstm.hidden_size),
            "num_layers": int(model.lstm.num_layers),
            # MC Dropout推論では実際のdropout率が必要なため、学習時に指定された
            # 値をそのまま保存する。なお _LSTMNet はFC前に独立したnn.Dropout層を
            # 持たないため、この値を復元してもMC Dropoutの分散は基本的にゼロのままである
            # （許容される劣化）
            "dropout": float(model.dropout_rate),
        }
