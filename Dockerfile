# syntax=docker/dockerfile:1
# Local AI Audit Assistant — Oracle A1 (ARM64) 데모 배포용 멀티스테이지 빌드
# 빌드: docker compose build  /  플랫폼: linux/arm64 (Ampere A1)

# ---- builder: uv로 의존성만 .venv에 설치 ----
FROM python:3.11-slim AS builder

# uv 바이너리 복사 (멀티아키 이미지)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# 일부 패키지(kiwipiepy 등) ARM 컴파일 대비 빌드 도구
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# 의존성 레이어 캐싱: 잠금파일만 먼저 복사 후 설치 (코드 변경과 분리)
# 런타임 그룹만 설치 — llm(Phase3 removed)·dev 제외
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
        --group core --group dashboard --group ml --group nlp --group export

# ---- runtime: 경량 이미지에 .venv + 코드만 ----
FROM python:3.11-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 비루트 실행 (보안)
RUN useradd -m -u 1000 appuser

# 의존성 환경 복사
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
# 앱 코드 복사 (.dockerignore로 data/·datasynth·tests 등 제외)
COPY --chown=appuser:appuser . /app

USER appuser

EXPOSE 8501

# nginx 뒤에서 headless 구동. 데이터는 /app/data 에 bind mount.
CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
