"""잠재공간 시각화 — VAE 잠재 벡터의 t-SNE 2D 산점도.

Why: VAE 잠재 공간이 정상/이상을 분리하는지 시각적으로 확인.
     모델 디버깅 및 대시보드 보고서용.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from matplotlib import pyplot as plt
from matplotlib.figure import Figure
from sklearn.manifold import TSNE
from sklearn.pipeline import Pipeline


def extract_latent_vectors(
    vae_pipeline: Pipeline, df: pd.DataFrame,
) -> np.ndarray:
    """VAE 파이프라인에서 잠재 벡터(mu) 추출.

    Why: 재매개변수화(reparameterize)는 랜덤 샘플링이므로,
         deterministic한 mu 벡터만 추출하여 일관된 시각화 보장.
    """
    preprocessor = vae_pipeline[:-1]
    X_transformed = np.array(preprocessor.transform(df), dtype=np.float32)

    vae_detector = vae_pipeline.named_steps["detector"]
    device = vae_detector._resolve_device()
    model = vae_detector.model_
    model.eval()
    model.to(device)

    tensor = torch.from_numpy(X_transformed).to(device)
    with torch.no_grad():
        mu, _ = model.encode(tensor)
    return mu.cpu().numpy()


def plot_latent_2d(
    latent: np.ndarray,
    labels: np.ndarray | None = None,
    perplexity: float = 30.0,
    random_state: int = 42,
) -> Figure:
    """t-SNE로 잠재 벡터를 2D 축소하여 산점도 생성.

    Args:
        latent: (n_samples, latent_dim) 잠재 벡터.
        labels: 0/1 배열 (정상/이상). None이면 단색.
        perplexity: t-SNE perplexity (기본 30).
        random_state: 재현성 시드.
    """
    reducer = TSNE(
        n_components=2, perplexity=perplexity,
        random_state=random_state, init="pca",
    )
    coords = reducer.fit_transform(latent)

    fig, ax = plt.subplots(figsize=(8, 6))
    if labels is not None:
        normal_mask = labels == 0
        ax.scatter(
            coords[normal_mask, 0], coords[normal_mask, 1],
            c="steelblue", alpha=0.4, s=10, label="Normal",
        )
        ax.scatter(
            coords[~normal_mask, 0], coords[~normal_mask, 1],
            c="crimson", alpha=0.8, s=30, label="Anomaly", marker="x",
        )
        ax.legend()
    else:
        ax.scatter(coords[:, 0], coords[:, 1], c="steelblue", alpha=0.4, s=10)

    ax.set_title("VAE Latent Space (2D)")
    ax.set_xlabel("Dim 1")
    ax.set_ylabel("Dim 2")
    plt.tight_layout()
    return fig
