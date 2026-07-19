"""PyTorch Variational Autoencoder used by the audit anomaly detector."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812


class AuditVAE(nn.Module):
    """Small fully connected VAE for tabular reconstruction scoring."""

    def __init__(self, input_dim: int, latent_dim: int = 8, hidden_dim: int = 32):
        super().__init__()
        self.input_dim = input_dim
        self.latent_dim = latent_dim
        self.hidden_dim = hidden_dim

        self.fc_hidden = nn.Linear(input_dim, hidden_dim)
        self.fc_mu = nn.Linear(hidden_dim, latent_dim)
        self.fc_logvar = nn.Linear(hidden_dim, latent_dim)

        self.fc_decode_hidden = nn.Linear(latent_dim, hidden_dim)
        self.fc_output = nn.Linear(hidden_dim, input_dim)

    def encode(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = F.relu(self.fc_hidden(x))
        return self.fc_mu(h), self.fc_logvar(h)

    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
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
    beta: float = 1.0,
    feature_groups: list[str] | None = None,
    group_weights: dict[str, float] | None = None,
) -> torch.Tensor:
    """VAE loss = reconstruction MSE + beta-weighted KL divergence."""
    recon_loss, kl_loss = vae_loss_components(
        recon,
        x,
        mu,
        logvar,
        feature_groups=feature_groups,
        group_weights=group_weights,
    )
    return recon_loss + (float(beta) * kl_loss)


def vae_loss_components(
    recon: torch.Tensor,
    x: torch.Tensor,
    mu: torch.Tensor,
    logvar: torch.Tensor,
    feature_groups: list[str] | None = None,
    group_weights: dict[str, float] | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return reconstruction and KL terms separately for diagnostics."""
    sq = (recon - x) ** 2
    recon_loss = _group_weighted_reconstruction_loss(
        sq,
        feature_groups=feature_groups,
        group_weights=group_weights,
    )
    kl_loss = -0.5 * torch.mean(1 + logvar - mu.pow(2) - logvar.exp())
    return recon_loss, kl_loss


def _group_weighted_reconstruction_loss(
    squared_error: torch.Tensor,
    *,
    feature_groups: list[str] | None = None,
    group_weights: dict[str, float] | None = None,
) -> torch.Tensor:
    if not feature_groups or len(feature_groups) != squared_error.shape[1]:
        return squared_error.mean()
    weights = group_weights or {}
    terms = []
    for group in sorted(set(feature_groups)):
        indices = [idx for idx, value in enumerate(feature_groups) if value == group]
        if not indices:
            continue
        group_error = squared_error[:, indices].mean()
        terms.append(group_error * float(weights.get(group, 1.0)))
    if not terms:
        return squared_error.mean()
    return torch.stack(terms).mean()
