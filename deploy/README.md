# Oracle A1 (ARM64) 데모 배포 가이드

입사 담당자에게 `http://공인IP` + basic auth로 풀스택 데모를 보여주기 위한 배포 절차.
생성기·합성데이터·회사 DB는 git에 없으며 서버 디스크에만 둔다.

관련 설계: [dev/active/oracle-arm-demo-deploy/plan.md](../dev/active/oracle-arm-demo-deploy/plan.md)

## 사전 조건

- Oracle Cloud `VM.Standard.A1.Flex` (ARM64), Docker + Docker Compose 설치
- 코드 clone 완료 (`data/`·`tools/datasynth/`는 git에 없음 → 서버에서 별도 주입)

## 1. ARM 의존성 검증 (선결 — 풀데모 가능 여부)

빌드 전 ARM64에서 무거운 ML 휠이 설치되는지 확인한다.

```bash
uv sync --frozen --no-dev \
    --group core --group dashboard --group ml --group nlp --group export
```

- `torch`: PyPI aarch64 CPU 휠 제공 → 정상
- `kiwipiepy`: aarch64 휠 부재 시 빌드 필요. 실패하면 nlp 경로 대안 검토 (plan 리스크 항목)

## 2. basic auth 비밀번호 생성 (커밋 금지)

```bash
# apache2-utils(htpasswd) 또는 openssl 사용
htpasswd -cB deploy/nginx/.htpasswd demo
# 비밀번호 입력 → deploy/nginx/.htpasswd 생성 (gitignore 처리됨)
```

## 3. 데모 데이터 업로드

로컬에서 서버로 데모 회사 데이터를 직접 전송 (git 미경유).

```bash
# 로컬 → 서버 (예시)
rsync -avz ./data/companies/<demo_company>/ \
    opc@<공인IP>:~/local-ai-assist/data/companies/<demo_company>/
```

`docker-compose.yml`의 `./data:/app/data` bind mount로 컨테이너에 주입된다.

## 4. Oracle 네트워크 개방 (가장 흔한 함정)

1. **VCN Ingress Rule**: Networking → VCN → Security List → Ingress 추가
   - Source `0.0.0.0/0`, Protocol TCP, Dest Port `80`
2. **인스턴스 iptables**: Oracle 이미지는 기본 차단
   ```bash
   sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
   sudo netfilter-persistent save   # 재부팅 유지
   ```

## 5. 기동

```bash
docker compose up -d --build
docker compose logs -f app          # 빌드/구동 로그 확인
```

→ 브라우저에서 `http://<공인IP>` 접속, basic auth 통과 후 대시보드 확인.

## 6. 상시 구동

- `restart: unless-stopped` 설정됨 → 크래시·재부팅 시 자동 복구
- Docker 데몬 부팅 자동시작: `sudo systemctl enable docker`

## 자산 보호 체크

- 이미지에 `data/`·`tools/datasynth/` 미포함 (`.dockerignore`)
- 데이터는 빌드가 아닌 런타임 bind mount로만 주입
- `.htpasswd`는 gitignore → 서버에서만 생성
