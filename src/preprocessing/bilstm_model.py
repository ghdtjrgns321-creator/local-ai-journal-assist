"""AuditBiLSTM — BiLSTM + Additive Attention PyTorch 모듈.

Why: 동일 입력자의 시간순 전표 시퀀스에서 '반복적 경영진 override' 패턴을
양방향 LSTM + attention이 자동 학습한다.
ISA 240 대응: 단일 전표가 아닌 시간적 맥락에서 이상을 판단.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class AdditiveAttention(nn.Module):
    """Additive (Bahdanau) Attention — 시퀀스 내 중요 시점에 집중.

    Why: 16-step 윈도우에서 이상 전표가 어느 시점에 있든 포착 가능.
    패딩된 위치는 masked_fill(-inf)로 attention weight를 0으로 만든다.
    """

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        # Why: learnable query — 전체 시퀀스에서 "이상 패턴"에 해당하는 표현을 학습
        self.query = nn.Parameter(torch.randn(hidden_dim))
        self.W = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.v = nn.Linear(hidden_dim, 1, bias=False)

    def forward(
        self,
        lstm_output: torch.Tensor,
        mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            lstm_output: (batch, seq_len, hidden_dim)
            mask: (batch, seq_len) bool — True=유효, False=패딩

        Returns:
            context: (batch, hidden_dim) — attention 가중합
            weights: (batch, seq_len) — attention 분포 (해석용)
        """
        # energy = v(tanh(W @ h + query)) — (batch, seq_len, 1)
        energy = self.v(torch.tanh(self.W(lstm_output) + self.query))
        energy = energy.squeeze(-1)  # (batch, seq_len)

        # Why: 패딩 위치의 energy를 -inf로 설정 → softmax 후 weight=0
        if mask is not None:
            energy = energy.masked_fill(~mask, float("-inf"))

        weights = torch.softmax(energy, dim=1)  # (batch, seq_len)

        # Why: bmm으로 가중합 — (batch, 1, seq_len) @ (batch, seq_len, hidden) → (batch, 1, hidden)
        context = torch.bmm(weights.unsqueeze(1), lstm_output).squeeze(1)
        return context, weights


class AuditBiLSTM(nn.Module):
    """BiLSTM + Additive Attention 시퀀스 분류기.

    Architecture:
        Input (batch, seq_len, input_size)
        → BiLSTM(hidden_size, bidirectional=True) → (batch, seq_len, hidden_size*2)
        → AdditiveAttention → (batch, hidden_size*2)
        → FC(hidden_size*2 → hidden_size) → ReLU → Dropout
        → FC(hidden_size → n_classes) → logits
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 64,
        n_classes: int = 2,
        dropout: float = 0.3,
        num_layers: int = 1,
    ) -> None:
        super().__init__()
        self.input_size = input_size

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            # Why: 단일 레이어 LSTM에서 inter-layer dropout은 무의미 → 0.0
            dropout=dropout if num_layers > 1 else 0.0,
        )
        lstm_out_dim = hidden_size * 2  # bidirectional 출력 차원
        self.attention = AdditiveAttention(lstm_out_dim)
        self.fc = nn.Sequential(
            nn.Linear(lstm_out_dim, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, n_classes),
        )

    def forward(
        self,
        x: torch.Tensor,
        mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """(batch, seq_len, input_size) → (batch, n_classes) logits."""
        lstm_out, _ = self.lstm(x)  # (batch, seq_len, hidden_size*2)
        context, self._attn_weights = self.attention(lstm_out, mask)
        return self.fc(context)
