"""ChromaDB 기반 스키마 학습기 — Vanna 대체 경량 RAG (스텁).

ChromaDB 미설치 시에도 text_to_sql.py는 정상 동작한다.
실제 구현은 별도 태스크에서 진행 예정.

사용 예시 (향후):
    trainer = SchemaTrainer(persist_dir="data/chromadb", embedding_client=client)
    trainer.train_ddl(SCHEMA_DDL)
    trainer.train_qa("월별 부정 전표 추이", "SELECT ...")
    results = trainer.search("부정 전표", n_results=3)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SchemaTrainer:
    """ChromaDB 기반 스키마 학습기 (스텁).

    TODO: ChromaDB + EmbeddingClient 연동 구현.
    """

    def __init__(self, persist_dir: str, embedding_client=None) -> None:
        self.persist_dir = persist_dir
        self.embedding_client = embedding_client
        logger.info("SchemaTrainer 스텁 초기화 (미구현)")

    def train_ddl(self, ddl_statements: dict[str, str]) -> None:
        """DDL을 임베딩하여 ChromaDB에 저장 (미구현)."""
        raise NotImplementedError("ChromaDB RAG 학습 미구현")

    def train_qa(self, question: str, sql: str) -> None:
        """Q&A 쌍을 임베딩하여 저장 (미구현)."""
        raise NotImplementedError("ChromaDB RAG 학습 미구현")

    def search(self, question: str, n_results: int = 3) -> list[dict]:
        """유사 질문 검색 → 참조 SQL 반환 (미구현)."""
        raise NotImplementedError("ChromaDB RAG 검색 미구현")
