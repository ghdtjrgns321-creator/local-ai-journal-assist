"""sklearn-compatible VAE anomaly scorer."""

from __future__ import annotations

import io
import logging

import numpy as np
import torch
from sklearn.base import BaseEstimator
from sklearn.utils.validation import check_is_fitted
from torch.utils.data import DataLoader, TensorDataset

from src.preprocessing.vae_model import AuditVAE, vae_loss, vae_loss_components

logger = logging.getLogger(__name__)


class VAEDetector(BaseEstimator):
    """VAE reconstruction-error detector with mini-batch training."""

    def __init__(
        self,
        hidden_dim: int = 32,
        latent_dim: int = 8,
        epochs: int = 50,
        batch_size: int = 256,
        lr: float = 1e-3,
        beta: float = 1.0,
        contamination: float = 0.02,
        device: str = "auto",
        posterior_collapse_ratio_threshold: float = 1e-4,
        feature_groups: list[str] | None = None,
        group_weights: dict[str, float] | None = None,
        group_loss_dominance_threshold: float = 0.75,
    ):
        self.hidden_dim = hidden_dim
        self.latent_dim = latent_dim
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.beta = beta
        self.contamination = contamination
        self.device = device
        self.posterior_collapse_ratio_threshold = posterior_collapse_ratio_threshold
        self.feature_groups = feature_groups
        self.group_weights = group_weights
        self.group_loss_dominance_threshold = group_loss_dominance_threshold

    def _resolve_device(self) -> str:
        if self.device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return self.device

    def fit(self, X, y=None):  # noqa: ARG002
        X = np.array(X, dtype=np.float32)
        device = self._resolve_device()
        self.model_ = AuditVAE(X.shape[1], self.latent_dim, self.hidden_dim).to(device)
        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)
        loader = DataLoader(
            TensorDataset(torch.from_numpy(X)),
            batch_size=max(int(self.batch_size), 1),
            shuffle=True,
        )

        self.model_.train()
        epoch_diagnostics: list[dict[str, float]] = []
        for _ in range(int(self.epochs)):
            epoch_diagnostics.append(self._fit_one_epoch(loader, optimizer, device))

        errors = self._compute_errors(X, device)
        percentile = (1 - self.contamination) * 100
        self.threshold_ = float(np.percentile(errors, percentile))
        self.classes_ = np.array([0, 1])
        self.training_diagnostics_ = self._build_training_diagnostics(
            X,
            epoch_diagnostics,
        )
        return self

    def _fit_one_epoch(self, loader, optimizer, device: str) -> dict[str, float]:
        total_loss = 0.0
        total_recon = 0.0
        total_kl = 0.0
        total_rows = 0
        for (batch_cpu,) in loader:
            batch = batch_cpu.to(device)
            recon, mu, logvar = self.model_(batch)
            recon_loss, kl_loss = vae_loss_components(
                recon,
                batch,
                mu,
                logvar,
                feature_groups=self.feature_groups,
                group_weights=self.group_weights,
            )
            loss = vae_loss(
                recon,
                batch,
                mu,
                logvar,
                beta=self.beta,
                feature_groups=self.feature_groups,
                group_weights=self.group_weights,
            )
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            n_rows = int(len(batch))
            total_rows += n_rows
            total_loss += float(loss.detach().cpu()) * n_rows
            total_recon += float(recon_loss.detach().cpu()) * n_rows
            total_kl += float(kl_loss.detach().cpu()) * n_rows
        if total_rows == 0:
            return {
                "loss": 0.0,
                "reconstruction_loss": 0.0,
                "kl_loss": 0.0,
                "kl_to_reconstruction_ratio": 0.0,
            }
        recon_mean = total_recon / total_rows
        kl_mean = total_kl / total_rows
        return {
            "loss": total_loss / total_rows,
            "reconstruction_loss": recon_mean,
            "kl_loss": kl_mean,
            "kl_to_reconstruction_ratio": kl_mean / max(recon_mean, 1e-12),
        }

    def _build_training_diagnostics(
        self,
        X: np.ndarray,
        epoch_diagnostics: list[dict[str, float]],
    ) -> dict:
        final = epoch_diagnostics[-1] if epoch_diagnostics else {}
        ratio = float(final.get("kl_to_reconstruction_ratio", 0.0))
        per_group_loss = self._compute_group_reconstruction_loss(X)
        dominant_group = self._dominant_group(per_group_loss)
        warnings: list[str] = []
        if ratio < float(self.posterior_collapse_ratio_threshold):
            warnings.append("posterior_collapse_warning")
        if dominant_group is not None:
            dominance_ratio = _dominance_ratio(per_group_loss)
            if dominance_ratio >= float(self.group_loss_dominance_threshold):
                warnings.append("group_loss_dominated")
        return {
            "hidden_dim": int(self.hidden_dim),
            "latent_dim": int(self.latent_dim),
            "epochs": int(self.epochs),
            "batch_size": int(self.batch_size),
            "batch_count": int(np.ceil(len(X) / max(int(self.batch_size), 1))),
            "lr": float(self.lr),
            "beta": float(self.beta),
            "n_samples": int(len(X)),
            "reconstruction_loss": float(final.get("reconstruction_loss", 0.0)),
            "kl_loss": float(final.get("kl_loss", 0.0)),
            "kl_to_reconstruction_ratio": ratio,
            "per_group_reconstruction_loss": per_group_loss,
            "dominant_group": dominant_group,
            "group_loss_dominance_ratio": _dominance_ratio(per_group_loss),
            "group_weights": dict(self.group_weights or {}),
            "warnings": warnings,
            "epoch_diagnostics": epoch_diagnostics,
        }

    def _compute_group_reconstruction_loss(self, X: np.ndarray) -> dict[str, float]:
        groups = _normalized_feature_groups(self.feature_groups, X.shape[1])
        if not groups:
            return {}
        per_feature = self._compute_errors_per_feature(X, self._resolve_device())
        result: dict[str, float] = {}
        for group in sorted(set(groups)):
            indices = [idx for idx, value in enumerate(groups) if value == group]
            if indices:
                result[group] = float(per_feature[:, indices].mean())
        return result

    @staticmethod
    def _dominant_group(per_group_loss: dict[str, float]) -> str | None:
        if not per_group_loss:
            return None
        return max(per_group_loss, key=per_group_loss.get)

    def _compute_errors_per_feature(self, X: np.ndarray, device: str) -> np.ndarray:
        self.model_.eval()
        self.model_.to(device)
        per_feature: list[np.ndarray] = []
        tensor = torch.from_numpy(np.array(X, dtype=np.float32))
        with torch.no_grad():
            for start in range(0, len(tensor), self.batch_size):
                batch = tensor[start : start + self.batch_size].to(device)
                mu, _ = self.model_.encode(batch)
                recon = self.model_.decode(mu)
                sq = (recon - batch) ** 2
                per_feature.append(sq.cpu().numpy())
        return np.concatenate(per_feature, axis=0)

    def _compute_errors(self, X: np.ndarray, device: str) -> np.ndarray:
        return self._compute_errors_per_feature(X, device).mean(axis=1)

    def predict(self, X) -> np.ndarray:
        check_is_fitted(self, ["model_", "threshold_"])
        device = self._resolve_device()
        errors = self._compute_errors(np.array(X, dtype=np.float32), device)
        return (errors > self.threshold_).astype(int)

    def score_samples(self, X) -> np.ndarray:
        check_is_fitted(self, ["model_", "threshold_"])
        device = self._resolve_device()
        return self._compute_errors(np.array(X, dtype=np.float32), device)

    def score_samples_per_feature(self, X) -> np.ndarray:
        check_is_fitted(self, ["model_", "threshold_"])
        device = self._resolve_device()
        return self._compute_errors_per_feature(
            np.array(X, dtype=np.float32),
            device,
        )

    def predict_proba(self, X) -> np.ndarray:
        check_is_fitted(self, ["model_", "threshold_"])
        device = self._resolve_device()
        errors = self._compute_errors(np.array(X, dtype=np.float32), device)
        scale = max(self.threshold_ * 0.1, 1e-8)
        prob_anomaly = 1.0 / (1.0 + np.exp(-(errors - self.threshold_) / scale))
        return np.column_stack([1 - prob_anomaly, prob_anomaly])

    def __getstate__(self):
        state = self.__dict__.copy()
        if "model_" in state:
            buf = io.BytesIO()
            torch.save(state["model_"].state_dict(), buf)
            state["_model_bytes"] = buf.getvalue()
            state["_input_dim"] = state["model_"].input_dim
            del state["model_"]
        return state

    def __setstate__(self, state):
        if "_model_bytes" in state:
            model = AuditVAE(
                state["_input_dim"],
                state["latent_dim"],
                state.get("hidden_dim", 32),
            )
            buf = io.BytesIO(state["_model_bytes"])
            model.load_state_dict(torch.load(buf, weights_only=True))
            model.eval()
            state["model_"] = model
            del state["_model_bytes"], state["_input_dim"]
        self.__dict__.update(state)


def _normalized_feature_groups(feature_groups: list[str] | None, n_features: int) -> list[str]:
    if not feature_groups or len(feature_groups) != n_features:
        return []
    return [str(group or "unknown") for group in feature_groups]


def _dominance_ratio(per_group_loss: dict[str, float]) -> float:
    if len(per_group_loss) <= 1:
        return 0.0
    total = sum(max(float(value), 0.0) for value in per_group_loss.values())
    if total <= 0:
        return 0.0
    return max(float(value) for value in per_group_loss.values()) / total
