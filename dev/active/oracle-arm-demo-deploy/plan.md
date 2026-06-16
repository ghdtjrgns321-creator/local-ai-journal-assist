# Oracle A1 (ARM) Docker Compose 데모 배포 Plan

## 목표

입사 담당자가 URL 클릭만으로 Local AI Audit Assistant 풀스택(Phase1 + Phase2 ML)을
실제 동작 화면으로 확인할 수 있게 한다. DataSynth 생성기·합성 데이터·회사 DB는 git에
올리지 않고 서버에만 두어 자산을 보호한다.

## 핵심 원칙

- git 레포: 코드 + 배포 설정(Dockerfile, compose, nginx)만. 데이터/생성기 제외 유지.
- 데이터 주입: 서버에 직접 scp/rsync → 컨테이너에 bind mount.
- 구동: Docker Compose (streamlit + nginx 2 서비스).
- 접근 보호: nginx basic auth + http://공인IP (도메인 없이 데모, 무단접근 차단). [결정 2026-06-02]
- 시점: Streamlit UI 개발 진행 중 → 실제 기동·데이터 업로드는 UI 완성 후. 인프라 설계만 선확정.

## 아키텍처

```
[입사담당자 브라우저]
        |
   80/443 (Oracle VCN ingress + iptables 개방)
        |
   [nginx 컨테이너]  ── basic auth, reverse proxy
        |  proxy_pass http://app:8501
   [streamlit 컨테이너 (app)]  ── uv multi-stage, ARM64
        |  bind mount
   [호스트 /opt/audit-demo/data]  ── 서버에 직접 올린 데모 데이터
```

- 데이터 경로: 앱이 `PROJECT_ROOT/data/...` 상대 경로 사용 → 컨테이너 `/app/data`에 bind mount.
- torch: PyPI 기본 인덱스 ARM64 CPU 휠 (서버 추론 CPU).

## 단계별 태스크

| # | 단계 | 산출물 | 상태 |
|---|------|--------|------|
| 1 | ARM 의존성 설치 검증 | 서버에서 `uv sync --group ml` 성공 확인 (torch/xgboost/lightgbm aarch64) | ⬜ |
| 2 | Dockerfile 작성 | uv 멀티스테이지, python:3.11-slim, ARM64 (`Dockerfile`) | ✅ |
| 3 | .dockerignore 작성 | data/·생성기·캐시·.git 제외 (`.dockerignore`) | ✅ |
| 4 | docker-compose.yml 작성 | app + nginx 서비스, bind mount, restart 정책 (`docker-compose.yml`) | ✅ |
| 5 | nginx 설정 + basic auth | reverse proxy conf (`deploy/nginx/nginx.conf`) + 절차 (`deploy/README.md`) | ✅ |
| 6 | Oracle 네트워크 개방 | VCN ingress rule + 인스턴스 iptables 80/443 | ⬜ |
| 7 | 데모 데이터 업로드 | scp/rsync → /opt/audit-demo/data | ⬜ |
| 8 | 기동·검증 | `docker compose up -d` → URL 접속 확인 | ⬜ |
| 9 | 상시 구동 | restart: unless-stopped + 재부팅 자동시작 확인 | ⬜ |

## 미결정 / 리스크

| 항목 | 내용 | 결정 필요 |
|------|------|-----------|
| 도메인/HTTPS | ✅ http://공인IP + basic auth 확정 (도메인 없음) | 완료 |
| 데모 데이터 | UI 완성 후 결정 (신규 데모 회사 vs 기존 재사용) | 보류 |
| ARM torch | 실제 서버 설치 성공 여부 (풀데모 선결 조건) | 서버 검증 |
| 브랜치 | 배포 설정 파일 커밋 브랜치 (현재 working tree에 phase2/datasynth 미커밋 변경 잔존) | 사용자 |

## 자산 보호 검증 (.dockerignore + .gitignore 이중)

- `.gitignore`: tools/datasynth/, data/* (이미 적용됨)
- `.dockerignore`: data/, tools/datasynth/ 제외 → 빌드 컨텍스트에도 미포함
- 데이터는 빌드가 아닌 런타임 bind mount로만 주입
