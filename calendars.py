#!/usr/bin/env python3
"""
calendars.py — 외부 캘린더(구글/네이버/Dooray 등) ics URL을 읽어 일정 이벤트로 변환.
hermes briefing.py에서 import. 비밀번호 없이 ics(읽기전용) URL만 사용.

ENV (Railway Variables):
  CALENDAR_ICS_URLS   여러 ics URL을 콤마(,)로 구분. 라벨 붙이려면 "라벨|URL" 형식도 가능.
                      예) "구글|https://...ics, 네이버|https://...ics, Dooray|https://...ics"
  (또는 개별로) GCAL_ICS_URL / NCAL_ICS_URL / DOORAY_ICS_URL

산출:
  fetch_events(today, horizon_days) -> [{date, time, title, label, location}]
  반복 일정(RRULE)도 기간 내로 전개. 종일/시간 일정 모두 처리.
실패해도 죽지 않음 — 캘린더 하나 실패하면 그것만 건너뛰고 나머지로 진행.
"""
from __future__ import annotations
import os
import datetime as _dt

KST = _dt.timezone(_dt.timedelta(hours=9))


def _sources() -> list[tuple[str, str]]:
    """(label, url) 목록. CALENDAR_ICS_URLS 우선, 없으면 개별 ENV."""
    out = []
    multi = os.environ.get("CALENDAR_ICS_URLS", "").strip()
    if multi:
        for chunk in multi.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "|" in chunk:
                label, url = chunk.split("|", 1)
                out.append((label.strip(), url.strip()))
            else:
                out.append(("캘린더", chunk))
    for env, label in [("GCAL_ICS_URL", "구글"),
                       ("NCAL_ICS_URL", "네이버"),
                       ("DOORAY_ICS_URL", "Dooray")]:
        u = os.environ.get(env, "").strip()
        if u:
            out.append((label, u))
    return out


def _to_date(v):
    """date 또는 datetime → (date, time_str|None)."""
    if isinstance(v, _dt.datetime):
        # tz 있으면 KST로 변환
        if v.tzinfo:
            v = v.astimezone(KST)
        return v.date(), v.strftime("%H:%M")
    if isinstance(v, _dt.date):
        return v, None
    return None, None


def fetch_events(today: _dt.date, horizon_days: int = 14) -> list[dict]:
    """모든 ics 소스에서 [today, today+horizon] 범위 이벤트 수집."""
    sources = _sources()
    if not sources:
        return []
    try:
        import httpx
        from icalendar import Calendar
    except ImportError:
        return []
    try:
        import recurring_ical_events
        has_recur = True
    except ImportError:
        has_recur = False

    start = today
    end = today + _dt.timedelta(days=horizon_days)
    events: list[dict] = []

    for label, url in sources:
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
                cal = Calendar.from_ical(r.content)
        except Exception:
            # 이 캘린더만 건너뜀 (브리핑 전체는 계속)
            continue

        try:
            if has_recur:
                # 반복 일정까지 기간 내로 전개
                occ = recurring_ical_events.of(cal).between(start, end)
                comps = occ
            else:
                comps = [c for c in cal.walk("VEVENT")]
        except Exception:
            comps = [c for c in cal.walk("VEVENT")]

        for ev in comps:
            try:
                dtstart = ev.get("DTSTART")
                if dtstart is None:
                    continue
                d, tm = _to_date(dtstart.dt)
                if d is None:
                    continue
                # 비반복 경로일 땐 직접 범위 필터
                if not has_recur and not (start <= d <= end):
                    continue
                title = str(ev.get("SUMMARY", "(제목 없음)"))
                loc = str(ev.get("LOCATION", "") or "")
                events.append({"date": d, "time": tm, "title": title,
                               "label": label, "location": loc})
            except Exception:
                continue

    events.sort(key=lambda e: (e["date"], e["time"] or "00:00"))
    return events


if __name__ == "__main__":
    t = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=9)).date()
    evs = fetch_events(t, 14)
    print(f"소스 {len(_sources())}개, 이벤트 {len(evs)}건")
    for e in evs[:20]:
        print(f"  {e['date']} {e['time'] or '종일'} [{e['label']}] {e['title']}")
