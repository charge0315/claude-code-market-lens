"""深層学習予測モデルのネットワーク構造定義（銘柄別モデル、P9）.

Market Lens `backend/services/dl/networks.py` から移植（変更なし）。BaseTorchPredictor は
学習ループ・標準化・保存/読込などの共通処理のみを持ち、ネットワークの中身を一切知らない設計のため、
モデルごとの `nn.Module` 実装はこのファイルのように独立して配置する。
"""

from __future__ import annotations

try:
    import torch
    import torch.nn as nn

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    TORCH_AVAILABLE = False


class _LSTMNet(nn.Module if TORCH_AVAILABLE else object):  # type: ignore[misc]
    """時系列予測用 LSTM ネットワーク."""

    def __init__(self, input_size: int, hidden_size: int, num_layers: int, dropout: float) -> None:
        super().__init__()
        # MC Dropout推論（_extract_arch_params経由での保存/復元）のため、
        # 構築時に指定された dropout 値を素の float 属性として公開しておく。
        # num_layers=1 では nn.LSTM 内部の dropout は 0 に強制されるが、
        # ここで保持するのは「指定値」であり、実効値の丸めは下の dropout= 引数側に閉じる。
        self.dropout_rate = dropout
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # noqa: F821
        # x: (batch, seq_len, input_size)
        out, _ = self.lstm(x)
        # 最後のタイムステップだけを使って予測
        return self.fc(out[:, -1, :]).squeeze(-1)


# 固定 Positional Encoding が事前生成する最大シーケンス長。
# 実データの窓は 10〜60 程度だが、将来的な窓拡張でも再確保不要とするため
# 十分な余裕（512）を確保しておく。メモリ負荷は (512, d_model) と軽微。
_MAX_SEQ_LEN = 512


class _TransformerNet(nn.Module if TORCH_AVAILABLE else object):  # type: ignore[misc]
    """時系列予測用の軽量 Encoder-only Transformer ネットワーク.

    株価日足のような小データ量では大規模 Transformer は過学習しやすいため、
    Decoder を持たず Encoder のみ・少層構成に絞る。Pre-LN（norm_first）を採り、
    浅い層でも勾配が安定して流れるようにしている。
    """

    def __init__(
        self,
        input_size: int,
        d_model: int,
        nhead: int,
        num_layers: int,
        dim_feedforward: int,
        dropout: float,
    ) -> None:
        super().__init__()
        # 後続の TransformerPredictor が保存済みモデルからアーキテクチャを
        # 復元できるよう、構成値を素の int 属性として公開しておく。
        self.d_model = d_model
        self.nhead = nhead
        self.num_layers = num_layers
        self.dim_feedforward = dim_feedforward
        # MC Dropout推論のため、学習時に実際に使われた dropout 率を保持する。
        # TransformerEncoderLayer 内の nn.Dropout はこの値で構築される
        self.dropout_rate = dropout

        # 特徴量次元をアテンションが扱う d_model 空間へ射影する。
        self.input_proj = nn.Linear(input_size, d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
            norm_first=True,
        )
        # Pre-LN 構成では nested tensor 最適化が無効化され警告が出るため、
        # 意図を明示して enable_nested_tensor=False を指定し警告を抑止する。
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers, enable_nested_tensor=False)
        self.fc = nn.Linear(d_model, 1)

        # 固定 sinusoidal PE は学習パラメータにせず buffer として保持する。
        # 位置情報は解析的に決まり学習の必要がないうえ、パラメータ化すると
        # 小データでは過学習要因になるため。
        self.register_buffer("pos_encoding", self._build_positional_encoding(d_model))

    @staticmethod
    def _build_positional_encoding(d_model: int) -> torch.Tensor:  # noqa: F821
        # Vaswani et al. の定式に従い (max_len, d_model) の固定 PE を生成する。
        position = torch.arange(_MAX_SEQ_LEN, dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float32) * (-torch.log(torch.tensor(10000.0)) / d_model)
        )
        pe = torch.zeros(_MAX_SEQ_LEN, d_model, dtype=torch.float32)
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        return pe

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # noqa: F821
        # x: (batch, seq_len, input_size)
        seq_len = x.size(1)
        # 射影後に実 seq_len 分だけ PE をスライスして加算する。
        h = self.input_proj(x) + self.pos_encoding[:seq_len].unsqueeze(0)
        # 窓全体が既知の過去データであり未来リークは起こり得ないため、
        # causal mask は付与せず全タイムステップ間の相互参照を許す。
        encoded = self.encoder(h)
        # 系列全体の平均プーリングで固定長ベクトルへ集約してから回帰する。
        pooled = encoded.mean(dim=1)
        return self.fc(pooled).squeeze(-1)
