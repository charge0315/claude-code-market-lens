"""深層学習（PyTorch）予測モデルの共通基盤クラス（銘柄別モデル、P9）.

Market Lens `backend/services/dl/base.py` から移植、変更点: マクロ指標特徴量
（`macro_df`/`use_macro_features`）・`feature_version` は移植しない（Alpha Forge の
`build_sequence_matrix` 自体がそれらを持たない回帰専用のため、`plans/04_タスクリスト.md` P9
参照）。学習ループ・train/val分割・標準化・early stopping・学習率スケジューリング・
保存/読込といった、どのネットワーク構造でも共通する処理を BaseTorchPredictor に集約する。
サブクラスはネットワーク構造（_build_network）とアーキテクチャパラメータの
抽出（_extract_arch_params）だけを実装すればよく、基盤側はネットワークの中身を一切知らない。
"""

from __future__ import annotations

import abc
import copy
import os
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    TORCH_AVAILABLE = False

from backend.services.learning.feature_engineering import build_sequence_matrix
from backend.services.learning.predictor_protocol import Hyperparams, PredictionOutput
from backend.services.learning.ts_validation import purged_train_val_split
from backend.services.ledger.skill_metrics import naive_rmse as _naive_rmse
from backend.services.ledger.skill_metrics import skill_score as _skill_score

# ── 学習に関するマジックナンバーを名前付き定数に集約 ─────────────────────────

# early stopping: val loss が本回数だけ連続で改善しなければ打ち切る
_EARLY_STOP_PATIENCE = 10
# 学習率スケジューラ（ReduceLROnPlateau）: 改善が停滞したとき学習率を半減させる
_LR_SCHEDULER_FACTOR = 0.5
_LR_SCHEDULER_PATIENCE = 5
# train/val分割で末尾から検証に回す比率
_DEFAULT_VAL_RATIO = 0.15
# 標準化で分母がゼロになるのを防ぐための微小値
_STD_EPSILON = 1e-8
# 推論時の信頼区間フォールバック値（residual_std を持たない旧モデル用）。
# 学習済みモデルは検証残差から動的に信頼区間を算出する。
_CONFIDENCE_INTERVAL = 0.025
# 95%信頼区間を正規分布近似で得るためのzスコア（±1.96σ）
_CONFIDENCE_Z_SCORE = 1.96
# 保存フォーマットのバージョン
_FORMAT_VERSION = 1
# MC Dropout推論時のstochastic forward pass回数。多いほど分布推定は安定するが
# 推論コストが線形に増えるため、単一シーケンスの推論用途として妥当な値に留める
_MC_DROPOUT_SAMPLES = 30
# MC標準偏差がこの値以下ならdropout層を持たない旧モデル等とみなし、
# 固定値信頼区間へフォールバックする（浮動小数点誤差を許容する閾値）
_MC_STD_NEGLIGIBLE_THRESHOLD = 1e-6

# pool_training_service.py の _MODEL_DIR / per_ticker_predictor.py の _DEFAULT_MODEL_DIR
# と同じ規約（このファイルから見てリポジトリ直下 data/models）
_DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[4] / "data" / "models"


class BaseTorchPredictor(abc.ABC):
    """PyTorch 予測モデルの共通基盤（抽象基底クラス）.

    学習済み重みや標準化統計量を保持するステートフルなサービスクラスであり、
    自身の状態（self.model 等）が学習/読込で変化するのは正常な設計。
    入力の DataFrame / 配列は破壊的に変更しない。
    """

    def __init__(self, model_dir: str | None = None) -> None:
        _require_torch()
        self.model_dir = model_dir or str(_DEFAULT_MODEL_DIR)
        os.makedirs(self.model_dir, exist_ok=True)

        self.model: nn.Module | None = None
        self.scaler_mean: np.ndarray | None = None
        self.scaler_std: np.ndarray | None = None
        self.seq_len: int = 30
        self.input_size: int = 0
        # 検証残差の標準偏差。学習後に held-out val 上で算出し、
        # 推論時の動的信頼区間の基準にする（旧モデルからのロード時は None）
        self.residual_std: float | None = None

    # ── サブクラスが実装する抽象メソッド ──────────────────────────────────

    @abc.abstractmethod
    def _build_network(self, arch_params: Hyperparams, input_size: int) -> nn.Module:
        """アーキテクチャパラメータからネットワークを構築する.

        学習時は train() 内の hyperparams から、ロード時は保存済み arch_params
        （または旧形式ファイルのフォールバック値）から呼ばれる。呼び出し元によって
        辞書のキーが必ずしも揃っているとは限らないため、必須キー前提を置かず
        .get(key, default) で値を取り出す実装にすること。
        """
        raise NotImplementedError

    @abc.abstractmethod
    def _extract_arch_params(self) -> Hyperparams:
        """現在の self.model からアーキテクチャパラメータを抽出する.

        save() 時に payload へ格納される。ここで返すキーは _build_network が
        そのまま受け取れる形式と一致させること（保存と再構築の対称性を保つ）。
        """
        raise NotImplementedError

    # ── 学習 ──────────────────────────────────────────────────────────────

    def train(
        self,
        df: pd.DataFrame,
        hyperparams: Hyperparams,
        forecast_horizon: int = 5,
    ) -> dict[str, float | str | int | bool]:
        """モデルを学習し、検証データ上の評価指標を返す.

        処理順序（正確性が最重要）:
        シーケンス生成 → train/val分割 → train統計量で標準化 → 学習
        （early stopping + LRスケジューラ）→ ベスト重み復元 → val指標算出。
        標準化統計量を分割「後」の train のみから計算することで、
        val期間の情報が統計量へ漏れる（リーク）のを防ぐ。
        """
        seq_len = int(hyperparams.get("seq_len", 30))
        epochs = int(hyperparams.get("epochs", 30))
        lr = float(hyperparams.get("lr", 1e-3))
        batch_size = int(hyperparams.get("batch_size", 32))
        self.seq_len = seq_len

        # 1. シーケンスデータ生成（標準化前の生の値）
        x_seq, y_arr, sample_dates = build_sequence_matrix(df, seq_len=seq_len, forecast_horizon=forecast_horizon)
        if y_arr is None:
            raise RuntimeError("predict_mode=False であれば y_arr は必ず生成される")

        # 2. 標準化より先に train/val分割する。gap でシーケンス窓の重複と
        #    ラベルの horizon リークを断ち切る
        gap = seq_len + forecast_horizon
        x_train_raw, y_train, x_val_raw, y_val = purged_train_val_split(
            x_seq, y_arr, val_ratio=_DEFAULT_VAL_RATIO, gap=gap
        )

        # 3. 標準化統計量は train 分割のみから計算する（val情報の混入を防ぐ）
        self.scaler_mean = x_train_raw.mean(axis=(0, 1))
        self.scaler_std = x_train_raw.std(axis=(0, 1)) + _STD_EPSILON
        x_train_norm = (x_train_raw - self.scaler_mean) / self.scaler_std
        x_val_norm = (x_val_raw - self.scaler_mean) / self.scaler_std

        self.input_size = x_train_norm.shape[2]
        self.model = self._build_network(hyperparams, input_size=self.input_size)

        x_train_t = torch.tensor(x_train_norm, dtype=torch.float32)
        y_train_t = torch.tensor(y_train, dtype=torch.float32)
        x_val_t = torch.tensor(x_val_norm, dtype=torch.float32)
        y_val_t = torch.tensor(y_val, dtype=torch.float32)

        # サンプル間シャッフルはシーケンス内部の時間構造を壊さないためリークにならず、
        # ミニバッチの偏りを減らして収束を安定させる
        train_loader = DataLoader(TensorDataset(x_train_t, y_train_t), batch_size=batch_size, shuffle=True)

        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        criterion = nn.MSELoss()
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, factor=_LR_SCHEDULER_FACTOR, patience=_LR_SCHEDULER_PATIENCE
        )

        best_val_loss = float("inf")
        best_state = copy.deepcopy(self.model.state_dict())
        epochs_without_improve = 0

        for _ in range(epochs):
            self.model.train()
            for xb, yb in train_loader:
                optimizer.zero_grad()
                loss = criterion(self.model(xb), yb)
                loss.backward()
                optimizer.step()

            # val は全件一括で評価する（DataLoader を挟まないことで KISS を優先）
            self.model.eval()
            with torch.no_grad():
                val_loss = float(criterion(self.model(x_val_t), y_val_t).item())

            scheduler.step(val_loss)

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_state = copy.deepcopy(self.model.state_dict())
                epochs_without_improve = 0
            else:
                epochs_without_improve += 1
                if epochs_without_improve >= _EARLY_STOP_PATIENCE:
                    break

        # 打ち切り・通常終了いずれの場合もベスト val 時点の重みへ復元する
        self.model.load_state_dict(best_state)

        self.model.eval()
        with torch.no_grad():
            val_pred = self.model(x_val_t).numpy()
            train_pred = self.model(x_train_t).numpy()

        metrics: dict[str, float | str | int | bool] = dict(_compute_metrics(y_val, val_pred))
        # train 上の RMSE も返し、val との乖離で過学習を診断できるようにする
        metrics["train_rmse"] = float(np.sqrt(np.mean((y_train - train_pred) ** 2)))

        # held-out val 上の残差ばらつきを保持し、推論時の動的信頼区間に使う。
        # in-sample（train）残差では過小評価になるため必ず val から計算する
        self.residual_std = float(np.std(y_val - val_pred))

        # 品質ゲート（per_ticker_training_service._apply_quality_gate）が新旧モデルを
        # 同じ検証窓で比較できるよう、val 区間の日付を記録する（per_ticker_predictor.train()
        # と同じキー体系）。DL は per_ticker_predictor と異なり val 分割後に全データ再学習を
        # 行わない（best val 重みをそのまま最終モデルとする）ため、ここで記録する
        # RMSE はそのまま出荷モデルの評価であり refit_full=False で明記する。
        n_samples = len(sample_dates)
        val_size = max(1, int(n_samples * _DEFAULT_VAL_RATIO))
        val_dates = sample_dates[n_samples - val_size :]
        metrics["eval_start"] = _iso_date(val_dates[0])
        metrics["eval_end"] = _iso_date(val_dates[-1])
        metrics["val_rows"] = int(val_size)
        metrics["refit_full"] = False

        return metrics

    # ── 推論 ──────────────────────────────────────────────────────────────

    def predict(self, df: pd.DataFrame, forecast_horizon: int = 5) -> PredictionOutput:
        """直近のシーケンスから将来の株価変化率を MC Dropout で予測する.

        学習時と同じ確率的forward passをT回繰り返し（MC Dropout）、
        予測分布（平均・標準偏差）を推定する。予測値には単一推論値ではなく
        分布の平均（mc_mean）を採用することで、dropoutノイズを平均化した
        安定した点推定を得る。

        信頼区間は「モデル自体の予測不確実性（mc_std）」と「学習時の検証残差
        （residual_std）」を分散として合成した total_std から算出する。
        dropout層を持たない旧アーキテクチャや旧モデル（mc_std≈0）で
        residual_std も無ければ、固定値 _CONFIDENCE_INTERVAL にフォールバックする。
        target_date は呼び出し側（ルーター）でカレンダー計算するため "TBD" を返す。
        """
        if self.model is None:
            raise ValueError("モデルがロードまたは学習されていません")

        x_seq, _, _ = build_sequence_matrix(
            df, seq_len=self.seq_len, forecast_horizon=forecast_horizon, predict_mode=True
        )
        x_norm = (x_seq - self.scaler_mean) / self.scaler_std

        # 最新シーケンスのみを推論に使う
        x_t = torch.tensor(x_norm[-1:], dtype=torch.float32)

        # MC Dropoutにはモデル全体を train() にする。
        # nn.Dropout サブモジュールだけを個別に train() へ切り替える手法は一見自然だが、
        # nn.TransformerEncoderLayer は「レイヤー自身が eval（self.training=False）」の
        # ときに融合カーネルによる高速パスへ分岐し、内部の nn.Dropout の training状態に
        # 関わらずdropoutそのものを一切適用しない（実測で確認済み）。本モデル群に
        # BatchNorm等の train/eval で意味が変わる層は無いため、モデル全体を train() に
        # することが全アーキテクチャで確実に確率的forward passを得る唯一の方法となる。
        # なお num_layers=1 の nn.LSTM は内部dropoutが構築時に0へ強制されるため
        # （_LSTMNet参照）、この場合のみMC分散は引き続きゼロになる（許容される劣化）。
        self.model.train()

        try:
            with torch.no_grad():
                mc_samples = np.array(
                    [float(self.model(x_t).item()) for _ in range(_MC_DROPOUT_SAMPLES)], dtype=np.float64
                )
        finally:
            # 後続の呼び出し（他ティッカーの予測等）へ確率的状態が漏れないよう必ず戻す
            self.model.eval()

        mc_mean = float(mc_samples.mean())
        mc_std = float(mc_samples.std())

        current_price = float(df["Close"].iloc[-1])
        predicted_price = current_price * (1.0 + mc_mean)

        # モデル予測の不確実性（mc_std）と検証残差（residual_std）は独立な
        # 誤差要因とみなし、分散を合成（sqrt(mc_std^2 + residual_std^2)）して
        # 信頼区間の幅に反映する。residual_std が無い旧モデルは mc_std のみで
        # 代用し、それも無視できるほど小さい（dropout層を持たない等）場合に限り
        # 固定値にフォールバックする段階的な劣化とする。
        if self.residual_std is not None:
            total_std = float(np.sqrt(mc_std**2 + self.residual_std**2))
            confidence = _CONFIDENCE_Z_SCORE * total_std
        elif mc_std > _MC_STD_NEGLIGIBLE_THRESHOLD:
            confidence = _CONFIDENCE_Z_SCORE * mc_std
        else:
            confidence = _CONFIDENCE_INTERVAL

        return {
            "target_date": "TBD",
            "predicted_close": predicted_price,
            "prediction_rate": mc_mean,
            "confidence_lower": predicted_price * (1.0 - confidence),
            "confidence_upper": predicted_price * (1.0 + confidence),
            "residual_std": self.residual_std,
        }

    def evaluate_on(self, df: pd.DataFrame, start: str, end: str, forecast_horizon: int = 5) -> dict[str, float]:
        """学習済み/ロード済みモデルを指定した日付区間で再評価する.

        per_ticker_predictor.BasePredictor.evaluate_on と同じ目的（品質ゲートでの新旧モデルの
        検証窓を揃える）。MC Dropout は使わず決定論的な forward pass（eval モード）で
        評価する点が predict() と異なる — 学習直後の val 指標算出（train() 内の
        val_pred）と同じ評価方法に揃えるため。
        """
        if self.model is None:
            raise ValueError("モデルがロードまたは学習されていません")

        x_seq, y_arr, sample_dates = build_sequence_matrix(df, seq_len=self.seq_len, forecast_horizon=forecast_horizon)
        if y_arr is None:
            raise RuntimeError("predict_mode=False であれば y_arr は必ず生成される")

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        mask = (sample_dates >= start_ts) & (sample_dates <= end_ts)
        if not mask.any():
            raise ValueError(f"指定区間にサンプルがありません（start={start}, end={end}）")

        x_norm = (x_seq[mask] - self.scaler_mean) / self.scaler_std
        x_t = torch.tensor(x_norm, dtype=torch.float32)

        self.model.eval()
        with torch.no_grad():
            pred = self.model(x_t).numpy()

        return _compute_metrics(y_arr[mask], pred)

    # ── 保存 / 読み込み ───────────────────────────────────────────────────

    def save(self, version: str) -> str:
        """モデルをディスクに保存し、パスを返す.

        ファイル名にクラス名を含めることで、サブクラスごとに保存物を区別できる。
        """
        if self.model is None:
            raise ValueError("学習済みモデルが存在しません")

        file_path = os.path.join(self.model_dir, f"{self.__class__.__name__}_{version}.pt")
        payload = {
            "format_version": _FORMAT_VERSION,
            "state_dict": self.model.state_dict(),
            "scaler_mean": self.scaler_mean,
            "scaler_std": self.scaler_std,
            "seq_len": self.seq_len,
            "input_size": self.input_size,
            "arch_params": self._extract_arch_params(),
            "residual_std": self.residual_std,
        }
        torch.save(payload, file_path)
        return file_path

    def load(self, file_path: str) -> None:
        """ディスクからモデルを読み込む."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"モデルファイルが見つかりません: {file_path}")

        # payload には np.ndarray（scaler_mean/std）を含むため weights_only=True 不可。
        # このファイルは save() で自アプリのみが書き込むローカルディレクトリのものであり、
        # 外部からアップロードされた信頼できないファイルを読み込むことはない。
        payload = torch.load(file_path, map_location="cpu", weights_only=False)  # nosec B614

        self.scaler_mean = payload["scaler_mean"]
        self.scaler_std = payload["scaler_std"]
        self.seq_len = payload["seq_len"]
        self.input_size = payload["input_size"]
        self.residual_std = payload.get("residual_std")

        self.model = self._build_network(payload["arch_params"], input_size=self.input_size)
        self.model.load_state_dict(payload["state_dict"])
        self.model.eval()


# ── ユーティリティ ────────────────────────────────────────────────────────


def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """RMSE / MAE / MAPE / naive_rmse / skill を算出する（MAPE はゼロ近傍の実値を除外）.

    naive_rmse・skill の意味は per_ticker_predictor.py の BasePredictor._calculate_metrics と
    同じ（skill_metrics.py に共通実装）。DL側でも「ナイーブ予測より良いか」を
    同じ基準で判定できるようにする。
    """
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    mae = float(np.mean(np.abs(y_true - y_pred)))
    # 実値がゼロに近いサンプルは相対誤差が発散するため MAPE 計算から除外する
    mask = np.abs(y_true) > _STD_EPSILON
    mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask]))) if mask.any() else 0.0
    naive = _naive_rmse(y_true)
    return {"rmse": rmse, "mae": mae, "mape": mape, "naive_rmse": naive, "skill": _skill_score(rmse, naive)}


def _iso_date(value: object) -> str:
    """pandas Timestamp 等の日付ライクな値を ISO 日付文字列（YYYY-MM-DD）に変換する.

    per_ticker_predictor.py の同名ヘルパーと役割は同じ（品質ゲートの日付区間比較用）。
    dl/base.py は per_ticker_predictor.py に依存しない設計のため、あえて重複させている。
    """
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return str(value)


def _require_torch() -> None:
    """PyTorch が未インストールの場合に分かりやすいエラーを出す."""
    if not TORCH_AVAILABLE:  # pragma: no cover
        raise RuntimeError(
            "PyTorch が未インストールです。"
            "'pip install torch --index-url https://download.pytorch.org/whl/cpu' を実行してください。"
        )
