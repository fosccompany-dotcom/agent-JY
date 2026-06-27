#!/usr/bin/env python3
"""
briefing.py — work-wiki(L4 운영층)를 스캔해 '오늘/임박 일정'을 모은다.
hermes main.py에서 import. 모델 호출 0 (순수 파일 파싱, 무료).

읽는 것:
  REPO_DIR/work-wiki/index.yaml         → active 영역 목록
  REPO_DIR/work-wiki/<area>/milestones.yaml → 게이트(날짜)
  REPO_DIR/work-wiki/<area>/tasks.yaml      → todo/blocked + due

산출:
  build_briefing(repo_dir, days=14) → 텔레그램용 HTML 문자열
  due_within(repo_dir, day) → 그 날(D-0) 또는 D-1 항목 (개별 알람용)
"""
from __future__ import annotations
import datetime as _dt
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def _today(tz_offset_hours: int = 9) -> _dt.date:
    """KST 기준 오늘 (Railway는 UTC라 +9)."""
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=tz_offset_hours)).date()


def _parse_date(v) -> _dt.date | None:
    if not v or v in ("null", "None"):
        return None
    if isinstance(v, _dt.date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _load_yaml(p: Path):
    if yaml is None or not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _active_areas(ww: Path) -> list[dict]:
    idx = _load_yaml(ww / "index.yaml")
    if not idx:
        return []
    areas = idx.get("areas", [])
    # 종료/아카이브 제외
    return [a for a in areas if str(a.get("status", "")).lower() not in ("종료", "archived", "done", "closed")]


def collect(repo_dir: str, days: int = 14):
    """전 영역에서 (날짜, 종류, 영역, 제목, 비고) 모음. 날짜 있는 것만."""
    ww = Path(repo_dir) / "work-wiki"
    today = _today()
    horizon = today + _dt.timedelta(days=days)
    rows = []
    overdue = []

    for area in _active_areas(ww):
        a = area.get("area")
        adir = ww / a
        title_area = area.get("title", a)

        # 1) milestones (게이트)
        ms = _load_yaml(adir / "milestones.yaml")
        if ms:
            for m in ms.get("milestones", []):
                d = _parse_date(m.get("date"))
                if not d:
                    continue
                item = {"date": d, "kind": "게이트", "area": a, "area_title": title_area,
                        "title": m.get("name", "?"), "note": m.get("note", ""),
                        "track": m.get("track", "")}
                if d < today:
                    overdue.append(item)
                elif d <= horizon:
                    rows.append(item)

        # 2) tasks (due 있는 todo/doing/blocked)
        ts = _load_yaml(adir / "tasks.yaml")
        if ts:
            for t in ts.get("tasks", []):
                st = str(t.get("status", "")).lower()
                if st in ("done", "cancelled"):
                    continue
                d = _parse_date(t.get("due"))
                if not d:
                    continue
                item = {"date": d, "kind": "할일", "area": a, "area_title": title_area,
                        "title": t.get("title", "?"), "note": t.get("id", ""),
                        "track": t.get("track", ""), "status": st}
                if d < today:
                    overdue.append(item)
                elif d <= horizon:
                    rows.append(item)

    rows.sort(key=lambda r: r["date"])
    overdue.sort(key=lambda r: r["date"])
    return today, rows, overdue


def _dday(today: _dt.date, d: _dt.date) -> str:
    n = (d - today).days
    if n == 0:
        return "D-DAY"
    if n > 0:
        return f"D-{n}"
    return f"D+{abs(n)}"


def build_briefing(repo_dir: str, days: int = 14) -> str:
    """아침 브리핑 / /today / /cal 공용 HTML. work-wiki 게이트 + 외부 캘린더 합침."""
    today, rows, overdue = collect(repo_dir, days)

    # 외부 캘린더(구글/네이버/Dooray) 이벤트 합치기 (실패해도 무시)
    cal_events = []
    try:
        import calendars
        cal_events = calendars.fetch_events(today, days)
    except Exception:
        cal_events = []
    # 캘린더 이벤트를 rows와 같은 형식으로 변환해 합침
    for e in cal_events:
        item = {"date": e["date"], "kind": "일정", "area": e["label"],
                "area_title": e["label"], "title": e["title"],
                "note": e.get("location", ""), "track": "",
                "time": e.get("time")}
        if e["date"] == today:
            rows.append(item)
        elif e["date"] > today:
            rows.append(item)
        # 과거 캘린더 일정은 표시 안 함 (이미 지난 약속)
    rows.sort(key=lambda r: (r["date"], r.get("time") or "00:00"))

    wd = ["월", "화", "수", "목", "금", "토", "일"][today.weekday()]
    src_note = "work-wiki" + (" + 캘린더" if cal_events else "")
    out = [f"<b>📅 {today.strftime('%Y-%m-%d')} ({wd}) 브리핑</b>",
           f"<i>{src_note}</i>"]

    # 지난 마감 (놓친 것 — work-wiki 게이트/할일만)
    if overdue:
        out.append("\n<b>⚠️ 지난 마감</b>")
        for r in overdue[:8]:
            tag = "🚩" if r.get("status") == "blocked" else "•"
            out.append(f"{tag} <code>{_dday(today, r['date'])}</code> [{r['area']}] {r['title']}")

    # 오늘
    todays = [r for r in rows if r["date"] == today]
    if todays:
        out.append("\n<b>🔥 오늘</b>")
        for r in todays:
            t = f"{r.get('time')} " if r.get("time") else ""
            out.append(f"• {t}[{r['area']}] {r['title']}")

    # 임박 (D+1 ~ horizon)
    soon = [r for r in rows if r["date"] > today]
    if soon:
        out.append(f"\n<b>⏰ 다가오는 {days}일</b>")
        cur = None
        for r in soon:
            if r["date"] != cur:
                cur = r["date"]
                swd = ["월","화","수","목","금","토","일"][cur.weekday()]
                out.append(f"\n<u>{cur.strftime('%m/%d')}({swd}) {_dday(today, cur)}</u>")
            if r["kind"] == "게이트":
                icon = "🎯"
            elif r["kind"] == "일정":
                icon = "📌"
            else:
                icon = "▫️"
            t = f"{r.get('time')} " if r.get("time") else ""
            out.append(f"{icon} {t}[{r['area']}] {r['title']}")

    if not (overdue or todays or soon):
        out.append("\n예정된 일정·게이트·마감이 없습니다.")

    out.append("\n—\n🎯게이트 📌캘린더 ▫️할일 🚩블록. 자세히: 영역명으로 물어보세요.")
    return "\n".join(out)


def due_alerts(repo_dir: str):
    """개별 알람용: 오늘(D-DAY)·내일(D-1) 항목만 추려서 반환 (리스트). 캘린더 포함."""
    today, rows, _ = collect(repo_dir, days=2)
    try:
        import calendars
        for e in calendars.fetch_events(today, 2):
            rows.append({"date": e["date"], "kind": "일정", "area": e["label"],
                         "title": e["title"], "time": e.get("time")})
    except Exception:
        pass
    hot = [r for r in rows if 0 <= (r["date"] - today).days <= 1]
    hot.sort(key=lambda r: (r["date"], r.get("time") or "00:00"))
    return today, hot


def build_alert(repo_dir: str) -> str | None:
    """D-DAY/D-1 있으면 짧은 알람 문자열, 없으면 None."""
    today, hot = due_alerts(repo_dir)
    if not hot:
        return None
    lines = ["<b>🔔 임박 알람</b>"]
    for r in hot:
        t = f"{r.get('time')} " if r.get("time") else ""
        lines.append(f"• <code>{_dday(today, r['date'])}</code> {t}[{r['area']}] {r['title']}")
    return "\n".join(lines)


if __name__ == "__main__":
    # 로컬 테스트: python briefing.py <repo_dir>
    import sys
    rd = sys.argv[1] if len(sys.argv) > 1 else "."
    print(build_briefing(rd))
    print("\n--- ALERT ---")
    print(build_alert(rd) or "(임박 없음)")
