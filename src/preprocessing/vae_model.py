"""Variational Autoencoder 네트워크 정의 (PyTorch).

Why: 정상 데이터의 분포를 학습한 뒤, reconstruction error가 큰 전표를
이상치로 탐지한다. 경량 아키텍처로 RTX 3070 Ti 8GB에서 ~2GB VRAM 사용.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class AuditVAE(nn.Module):
    """감사 전표 이상탐지용 Variational Autoencoder.

    아키텍처: input_dim → 64 → latent_dim → 64 → input_dim
    """

    def __init__(self, input_dim: int, latent_dim: int = 32):
        super().__init__()
        self.input_dim = input_dim
        self.latent_dim = latent_dim

        # 인코더: input → 64 → (mu, logvar)
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
        )
        self.fc_mu = nn.Linear(64, latent_dim)
        self.fc_logvar = nn.Linear(64, latent_dim)

        # 디코더: latent → 64 → input
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 64),
            nn.ReLU(),
            nn.Linear(64, input_dim),
        )

    def encode(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """입력 → 잠재 공간의 평균(mu)·분산(logvar)."""
        h = self.encoder(x)
        return self.fc_mu(h), self.fc_logvar(h)

    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        """Reparameterization trick: z = mu + eps * std."""
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        """잠재 벡터 → 재구성 출력."""
        return self.decoder(z)

    def forward(
        self, x: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """순전파: 입력 → (재구성, mu, logvar)."""
        mu, logvar = self.encode(x)
        z = self.reparameterize(mu, logvar)
        recon = self.decode(z)
        return recon, mu, logvar


def vae_loss(
    recon: torch.Tensor,
    x: torch.Tensor,
    mu: torch.Tensor,
    logvar: torch.Tensor,
) -> torch.Tensor:
    """VAE 손실 = reconstruction_loss(MSE) + KL_divergence.

    Why: MSE로 재구성 품질을 측정하고, KL로 잠재 공간이
    표준정규분포에 가깝도록 정규화한다.
    """
    recon_loss = nn.functional.mse_loss(recon, x, reduction="mean")
    kl_loss = -0.5 * torch.mean(1 + logvar - mu.pow(2) - logvar.exp())
    return recon_loss + kl_loss
