#!/usr/bin/env python3
"""
Hermes (owned edition) — VIVIAN_REPO 조종용 텔레그램 봇.
설계: 몸(텔레그램) + 손발(/명령 = 결정론적, 모델 호출 0) + 뇌(옵션, 기본 OFF).
토큰/키는 전부 환경변수로만 읽음. 코드에 자격증명 없음.

ENV (Railway Variables):
  TELEGRAM_BOT_TOKEN   (필수) BotFather 토큰 — 기존 봇과 같은 토큰 그대로
  ALLOWED_CHAT_ID      (권장) 본인 chat id만 허용. 비우면 누구나 명령 가능(비권장)
  GIT_REPO_URL         (권장) 데이터 레포 https URL (예: https://github.com/fosccompany-dotcom/Agent-vivian.git)
  GITHUB_TOKEN         (push용) repo 권한 PAT
  REPO_DIR             데이터 작업 경로 (기본: /app/work/Agent-vivian/vivian_repo)
  CHAT_ENABLED         "true"면 일반 메시지를 모델로 답함 (기본 false = 토큰 0)
  ANTHROPIC_API_KEY    CHAT_ENABLED일 때만 필요
  ANTHROPIC_MODEL      기본 claude-haiku-4-5-20251001 (가장 저렴, env로 교체 가능)
"""
import os, json, asyncio, subprocess, html
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          filters, ContextTypes)

TOKEN          = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID", "").strip()
GIT_REPO_URL   = os.environ.get("GIT_REPO_URL", "").strip()
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "").strip()
CLONE_ROOT     = Path(os.environ.get("CLONE_ROOT", "/app/work"))
REPO_DIR       = Path(os.environ.get("REPO_DIR", str(CLONE_ROOT / "Agent-vivian" / "vivian_repo")))
CHAT_ENABLED   = os.environ.get("CHAT_ENABLED", "false").lower() == "true"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL   = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")  # 균형. env로 교체 가능

HELP = (
    "<b>Hermes 명령</b> (모델 호출 0, 무료)\n"
    "/status  — 저장소 적재 현황 (manifest 요약)\n"
    "/ingest  — _inbox 처리 → L3 적재 → 커밋\n"
    "/pending — 판단 대기 항목 (needs_claude)\n"
    "/commit  — 변경분 git push\n"
    "/id      — 이 채팅 id (ALLOWED_CHAT_ID 설정용)\n"
    "/help    — 이 도움말\n\n"
    "📎 파일을 그냥 보내면 _inbox에 받아 자동 적재·푸시 (캡션 'work'=회사용)\n"
    f"뇌(자연어 대화): {'ON' if CHAT_ENABLED else 'OFF (토큰 절약)'}"
)

# ---------- helpers ----------
def is_allowed(update: Update) -> bool:
    if not ALLOWED_CHAT_ID:
        return True
    return str(update.effective_chat.id) == ALLOWED_CHAT_ID

def _sh(args, cwd=None) -> str:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=180)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip() or "(no output)"
    except Exception as e:
        return f"ERR: {e}"

async def sh(args, cwd=None) -> str:
    return await asyncio.to_thread(_sh, args, cwd)

def clip(s: str, n: int = 3500) -> str:
    return s if len(s) <= n else s[:n] + "\n…(truncated)"

def bootstrap_repo():
    """데이터 레포 확보. manifest.json 유무로 '진짜 받아졌는지' 판정.
    폴더만 있고 비었으면(이전 실패 잔재) 지우고 다시 clone."""
    import shutil
    # 이미 제대로 받아져 있으면 통과
    if (REPO_DIR / "manifest.json").exists():
        return "repo present (manifest ok)"
    if not (GIT_REPO_URL and GITHUB_TOKEN):
        return "repo missing & no clone creds (GIT_REPO_URL/GITHUB_TOKEN)"
    # git 설치 확인
    if shutil.which("git") is None:
        return "git not installed (check nixpacks.toml)"
    # 빈/불완전 폴더 잔재 제거 후 재clone
    if REPO_DIR.exists():
        shutil.rmtree(REPO_DIR, ignore_errors=True)
    REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
    url = GIT_REPO_URL.replace("https://", f"https://x-access-token:{GITHUB_TOKEN}@")
    out = _sh(["git", "clone", url, str(REPO_DIR)])
    _sh(["git", "config", "user.name", "hermes"], cwd=str(REPO_DIR))
    _sh(["git", "config", "user.email", "hermes@local"], cwd=str(REPO_DIR))
    ok = (REPO_DIR / "manifest.json").exists()
    return f"cloned ({'manifest ok' if ok else 'still no manifest'}): {out}"

# ---------- command handlers (NO model) ----------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    await update.message.reply_text(HELP, parse_mode=ParseMode.HTML)

async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"chat id: <code>{update.effective_chat.id}</code>",
                                    parse_mode=ParseMode.HTML)

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    mj = REPO_DIR / "manifest.json"
    if not mj.exists():
        await update.message.reply_text(f"manifest 없음: {mj}")
        return
    m = json.loads(mj.read_text(encoding="utf-8"))
    recs = m.get("records", [])
    raw = sum(1 for r in recs if r.get("type") == "raw")
    der = sum(1 for r in recs if r.get("type") == "derived-summary")
    layers = m.get("layers", {})
    msg = (f"<b>STATUS</b>\nrecords: {len(recs)} (raw {raw} / derived {der})\n"
           f"L1: {layers.get('L1_core',{}).get('status','?')}\n"
           f"L2: {layers.get('L2_archive',{}).get('status','?')}\n"
           f"L3: {layers.get('L3_raw',{}).get('status','?')}")
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_ingest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    await update.message.reply_text("적재 실행 중…")
    out = await sh(["python", "scripts/watch_inbox.py"], cwd=str(REPO_DIR))
    await update.message.reply_text(clip(out))

async def cmd_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    f = REPO_DIR / "tasks" / "needs_claude.md"
    txt = f.read_text(encoding="utf-8") if f.exists() else "판단 대기 항목 없음."
    await update.message.reply_text(clip(txt or "비어 있음"))

async def cmd_commit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    await sh(["git", "add", "-A"], cwd=str(REPO_DIR))
    await sh(["git", "commit", "-m", "[hermes] manual commit"], cwd=str(REPO_DIR))
    out = await sh(["git", "push"], cwd=str(REPO_DIR))
    await update.message.reply_text(clip("push:\n" + out))

async def cmd_pull(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """GitHub 최신을 받아 봇 저장소를 동기화 (웹에서 바뀐 것 반영)."""
    if not is_allowed(update): return
    await update.message.reply_text("⬇️ GitHub 최신 받는 중…")
    # 로컬 변경이 있으면 충돌나니, 안전하게 원격 기준으로 맞춤
    await sh(["git", "fetch", "origin"], cwd=str(REPO_DIR))
    out = await sh(["git", "reset", "--hard", "origin/main"], cwd=str(REPO_DIR))
    # 동기화 후 상태 한 줄
    head = await sh(["git", "log", "-1", "--oneline"], cwd=str(REPO_DIR))
    await update.message.reply_text(clip(f"✅ 동기화 완료\n{out}\nHEAD: {head}"))

# ---------- optional brain (OFF by default) ----------
async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """텔레그램으로 받은 파일을 _inbox에 저장 → 자동 적재·커밋·푸시.
    캡션에 'work' 포함 시 work 폴더, 아니면 personal."""
    if not is_allowed(update): return
    doc = update.message.document
    if not doc:
        return
    caption = (update.message.caption or "").lower()
    sub = "work" if "work" in caption else "personal"
    inbox = REPO_DIR / "_inbox" / sub
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / doc.file_name
    await update.message.reply_text(f"📥 받음: {doc.file_name} → _inbox/{sub}\n적재 시작…")
    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=str(dest))
    except Exception as e:
        await update.message.reply_text(f"다운로드 실패: {e}")
        return
    # 자동 적재 → 커밋 → 푸시
    out = await sh(["python", "scripts/watch_inbox.py"], cwd=str(REPO_DIR))
    await sh(["git", "add", "-A"], cwd=str(REPO_DIR))
    await sh(["git", "commit", "-m", f"[hermes] auto-ingest {doc.file_name}"], cwd=str(REPO_DIR))
    push = await sh(["git", "push"], cwd=str(REPO_DIR))
    await update.message.reply_text(clip(f"✅ 적재+푸시 완료\n{out}\npush: {push}"))

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    if not (CHAT_ENABLED and ANTHROPIC_API_KEY):
        await update.message.reply_text(
            "💤 자연어 대화는 OFF (토큰 절약). 명령은 /help.\n"
            "정리·판단 같은 무거운 건 Claude 챗에서 하세요.")
        return
    import httpx
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": ANTHROPIC_MODEL, "max_tokens": 800,
                      "messages": [{"role": "user", "content": update.message.text}]})
        data = r.json()
        txt = "".join(b.get("text", "") for b in data.get("content", [])) or f"(provider: {data})"
        await update.message.reply_text(clip(txt))
    except Exception as e:
        await update.message.reply_text(f"모델 호출 실패: {e}")

def main():
    print("bootstrap:", bootstrap_repo())
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ingest", cmd_ingest))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("commit", cmd_commit))
    app.add_handler(CommandHandler("pull", cmd_pull))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("Hermes (owned) up. chat brain:", "ON" if CHAT_ENABLED else "OFF")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
