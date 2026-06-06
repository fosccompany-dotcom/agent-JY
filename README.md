# Hermes (owned) — VIVIAN_REPO 조종 텔레그램 봇

같은 텔레그램 봇 토큰을 그대로 쓰되, **엔진을 네가 소유하는 코드로 교체**한 버전.
`/`명령 = 결정론적(모델 호출 0, 무료). 자연어 대화(뇌) = 기본 OFF.

## 구성
| 파일 | 역할 |
|---|---|
| `main.py` | 봇 본체 (명령 핸들러 + 옵션 뇌) |
| `requirements.txt` | python-telegram-bot, httpx |
| `Procfile` | Railway 실행 (`worker: python main.py`) |
| `.env.example` | 넣을 환경변수 목록 (실제 값은 커밋 금지) |

## 명령 (모델 0)
`/status` 적재현황 · `/ingest` _inbox 처리+커밋 · `/pending` 판단대기 · `/commit` push · `/id` chat id · `/help`

## 배포 순서 (Railway)
1. **데이터 레포 먼저:** `VIVIAN_REPO`를 `Agent-vivian` 레포에 `vivian_repo/`로 커밋
2. **이 봇 커밋:** 이 폴더(agent-JY)를 `agent-JY` 레포에 push
3. **기존 블랙박스 Hermes 서비스 STOP** (같은 토큰 두 곳이 폴링하면 충돌)
4. Railway → New service → Deploy from `agent-JY` repo
5. **Variables**에 `.env.example` 값 입력:
   - `TELEGRAM_BOT_TOKEN` (기존과 동일 토큰) — *너만 입력, 코드/채팅에 노출 금지*
   - `GIT_REPO_URL`, `GITHUB_TOKEN`, `ALLOWED_CHAT_ID`
   - `CHAT_ENABLED=false` (뇌 OFF 유지)
6. 배포 후 텔레그램에서 `/id` → 나온 값으로 `ALLOWED_CHAT_ID` 채우고 재배포(보안)
7. `/status`, `/ingest` 동작 확인

## cron (선택, ③ 반사신경) — 모델 0
Railway cron 또는 별도 워커에서 정기 적재:
```
*/10 * * * *  cd $REPO_DIR && python scripts/watch_inbox.py
```

## 비용
- `/`명령·cron = 모델 호출 0 → **API $0**, Railway 호스팅비만 (월 몇 달러)
- 뇌(자연어)는 `CHAT_ENABLED=true` + `ANTHROPIC_API_KEY` 넣을 때만 과금. 켤 땐 Haiku 권장 + Console 월 상한 낮게.

## 보안
- 토큰·PAT·API키는 **Railway Variables에만**. 코드/깃/채팅에 절대 넣지 말 것 (`.gitignore`에 `.env`).
- `ALLOWED_CHAT_ID` 설정해서 본인만 명령 가능하게.
