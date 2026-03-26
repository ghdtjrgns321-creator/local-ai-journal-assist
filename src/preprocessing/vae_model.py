"""AuditVAE — PyTorch Variational Autoencoder 네트워크.

Why: 정상 전표의 재구성 오차로 이상 전표를 탐지한다.
VAE는 잠재 공간이 정규분포를 따르도록 KL divergence를 추가하여
단순 오토인코더보다 안정적인 이상 탐지를 수행한다.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812


class AuditVAE(nn.Module):
    """감사 전표 이상 탐지용 VAE.

    Architecture: Input → Hidden(32) → Latent(mu, logvar)
                  Latent → Hidden(32) → Output(input_dim)
    """

    def __init__(self, input_dim: int, latent_dim: int = 8):
        super().__init__()
        self.input_dim = input_dim
        self.latent_dim = latent_dim

        # Encoder
        self.fc_hidden = nn.Linear(input_dim, 32)
        self.fc_mu = nn.Linear(32, latent_dim)
        self.fc_logvar = nn.Linear(32, latent_dim)

        # Decoder
        self.fc_decode_hidden = nn.Linear(latent_dim, 32)
        self.fc_output = nn.Linear(32, input_dim)

    def encode(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = F.relu(self.fc_hidden(x))
        return self.fc_mu(h), self.fc_logvar(h)

    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        """재매개변수화 트릭 — 역전파 가능하도록 샘플링."""
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        h = F.relu(self.fc_decode_hidden(z))
        return self.fc_output(h)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
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
    """VAE 손실 = MSE 재구성 오차 + KL divergence."""
    recon_loss = F.mse_loss(recon, x, reduction="mean")
    # KL(q(z|x) || p(z)) = -0.5 * Σ(1 + logvar - mu² - exp(logvar))
    kl_loss = -0.5 * torch.mean(1 + logvar - mu.pow(2) - logvar.exp())
    return recon_loss + kl_loss
