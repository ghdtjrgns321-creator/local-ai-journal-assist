"""AuditFTTransformer — FT-Transformer PyTorch 네트워크.

Why: 모든 피처를 토큰화하여 self-attention으로 피처 간 상호작용을 학습한다.
룰 결과 간 조합 패턴을 attention이 자동 학습한다.

Note: 범주형 피처는 전처리기(TargetEncoder/OrdinalEncoder)에서 수치 변환 후 입력됨.
      향후 실데이터 fine-tuning 시 CategoricalFeatureTokenizer(nn.Embedding) 분리 검토.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class FeatureTokenizer(nn.Module):
    """수치형 피처를 d_token 차원 벡터로 변환.

    Why: FT-Transformer는 각 피처를 독립 토큰으로 취급해야 한다.
    벡터화 연산으로 n_features개 Linear(1, d_token)을 한 번에 처리.
    """

    def __init__(self, n_features: int, d_token: int) -> None:
        super().__init__()
        # Why: 개별 nn.Linear 대신 파라미터 행렬로 벡터화 — GPU 효율 극대화
        self.weight = nn.Parameter(torch.empty(n_features, d_token))
        self.bias = nn.Parameter(torch.empty(n_features, d_token))
        nn.init.kaiming_uniform_(self.weight)
        nn.init.zeros_(self.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """(batch, n_features) → (batch, n_features, d_token)."""
        # x.unsqueeze(-1): (B, F, 1) * weight: (F, D) → (B, F, D)
        return x.unsqueeze(-1) * self.weight + self.bias


class AuditFTTransformer(nn.Module):
    """감사 전표 이상 탐지용 FT-Transformer.

    Architecture: FeatureTokenizer → [CLS] concat → TransformerEncoder → FC head
    n_features는 전처리 후 실제 출력 차원으로 동적 결정 (하드코딩 금지).
    """

    def __init__(
        self,
        n_features: int,
        n_classes: int = 2,
        d_token: int = 64,
        n_layers: int = 2,
        n_heads: int = 4,
        d_ff: int = 128,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.n_features = n_features
        self.tokenizer = FeatureTokenizer(n_features, d_token)

        # Why: [CLS] 토큰은 전체 피처의 요약 표현을 학습한다 (BERT 패턴)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_token))
        nn.init.normal_(self.cls_token, std=0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_token,
            nhead=n_heads,
            dim_feedforward=d_ff,
            dropout=dropout,
            batch_first=True,  # 입력: (B, seq_len, d_token)
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.head = nn.Linear(d_token, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """(batch, n_features) → (batch, n_classes) logits."""
        batch_size = x.size(0)

        # 피처 토큰화: (B, F) → (B, F, D)
        tokens = self.tokenizer(x)

        # [CLS] 토큰 결합: (B, 1, D) + (B, F, D) → (B, F+1, D)
        cls_expanded = self.cls_token.expand(batch_size, -1, -1)
        tokens = torch.cat([cls_expanded, tokens], dim=1)

        # Transformer 인코딩 → [CLS] 위치(0번) 추출
        encoded = self.encoder(tokens)
        cls_output = encoded[:, 0, :]  # (B, D)

        return self.head(cls_output)  # (B, n_classes)

    def forward_with_attention(
        self,
        x: torch.Tensor,
    ) -> tuple[torch.Tensor, list[torch.Tensor]]:
        """logits와 함께 각 layer의 [CLS]→피처 attention 가중치 반환.

        Why: nn.TransformerEncoder는 fast-path 최적화로 need_weights=True여도
             weights를 반환하지 않는 경우가 있어, 각 layer의 self_attn을
             수동 호출해 multi-head attention 평균을 추출한다.

        Returns:
            logits: (B, n_classes)
            attentions: list of (B, F+1, F+1) — layer 수만큼. [:,0,:]이
                [CLS] 토큰이 각 피처 토큰에 준 가중치.
        """
        batch_size = x.size(0)
        tokens = self.tokenizer(x)
        cls_expanded = self.cls_token.expand(batch_size, -1, -1)
        tokens = torch.cat([cls_expanded, tokens], dim=1)

        attentions: list[torch.Tensor] = []
        current = tokens
        # Why: encoder.layers를 순회하며 각 TransformerEncoderLayer를 수동 수행.
        #      norm_first=False (기본값) 가정 — post-LayerNorm 경로.
        for layer in self.encoder.layers:
            # Self-attention sub-block
            attn_out, attn_w = layer.self_attn(
                current,
                current,
                current,
                need_weights=True,
                average_attn_weights=True,  # head 평균 → (B, S, S)
            )
            current = layer.norm1(current + layer.dropout1(attn_out))
            # Feed-forward sub-block
            ff_out = layer.linear2(
                layer.dropout(layer.activation(layer.linear1(current))),
            )
            current = layer.norm2(current + layer.dropout2(ff_out))
            attentions.append(attn_w)

        cls_output = current[:, 0, :]
        logits = self.head(cls_output)
        return logits, attentions
