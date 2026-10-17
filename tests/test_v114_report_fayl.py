"""v114 testlari:
(1) Avto-hisobot TUGAGAN davrni yig'ishi (bo'sh-hisobot tuzatishi),
(2) /fayl damp formati (bitta fayl, OCRsiz),
(3) Inline tugmalar 2 tadan (yakka tugma qolmasligi),
(4) Versiya SINO-LAI-114.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.services.reports import (
    LOCAL_TZ,
    _period_bounds,
    completed_period_targets,
)
from app.services.channel_archive import format_dump_file
from app.bot import keyboards as KB


# ---------------------------------------------------------------
# (1) HISOBOT — TUGAGAN davr sanalari
# ---------------------------------------------------------------
def test_daily_target_is_completed_day_not_new_day():
    """Yarim tundan keyingi avto-hisobot KECHA ni yig'adi (bo'sh 'bugun' emas)."""
    now = datetime(2026, 10, 16, 19, 6, tzinfo=timezone.utc)   # Toshkent 17.10 00:06
    tg = completed_period_targets(now)
    assert tg["daily"] == date(2026, 10, 16)          # tugagan kun — 16-oktyabr
    assert tg["daily"] != now.astimezone(LOCAL_TZ).date()   # "bugun" emas!


def test_daily_bounds_cover_full_completed_day():
    """target_date berilganda kunlik oynasi 00:00→23:59 qamraydi."""
    yday = date(2026, 10, 16)
    s, e, _ = _period_bounds("daily", target_date=yday)
    s_l, e_l = s.astimezone(LOCAL_TZ), e.astimezone(LOCAL_TZ)
    assert s_l.date() == yday and s_l.hour == 0 and s_l.minute == 0
    assert e_l.date() == yday and e_l.hour == 23 and e_l.minute == 59


def test_weekly_target_is_last_completed_sunday():
    """Haftalik maqsad — tugagan yakshanba; oynasi Dush..Yak (7 kun)."""
    now = datetime(2026, 10, 18, 19, 6, tzinfo=timezone.utc)   # Toshkent 19.10 (dush) 00:06
    tg = completed_period_targets(now)
    assert tg["weekly"].weekday() == 6                         # yakshanba
    today_l = now.astimezone(LOCAL_TZ).date()
    assert 1 <= (today_l - tg["weekly"]).days <= 7
    s, e, _ = _period_bounds("weekly", target_date=tg["weekly"])
    assert s.astimezone(LOCAL_TZ).date() == tg["weekly"] - timedelta(days=6)  # dushanba
    assert e.astimezone(LOCAL_TZ).date() == tg["weekly"]                       # yakshanba


def test_monthly_target_is_previous_month():
    """Oylik maqsad — o'tgan oyning oxirgi kuni; oynasi butun oy."""
    now = datetime(2026, 11, 1, 19, 6, tzinfo=timezone.utc)    # Toshkent 02.11 00:06
    tg = completed_period_targets(now)
    assert (tg["monthly"].year, tg["monthly"].month) == (2026, 10)
    s, e, _ = _period_bounds("monthly", target_date=tg["monthly"])
    assert s.astimezone(LOCAL_TZ).date() == date(2026, 10, 1)
    assert e.astimezone(LOCAL_TZ).date() == date(2026, 10, 31)


def test_naive_datetime_treated_as_utc():
    now = datetime(2026, 10, 16, 19, 6)                        # tzsiz — UTC deb olinadi
    tg = completed_period_targets(now)
    assert tg["daily"] == date(2026, 10, 16)


# ---------------------------------------------------------------
# (2) /fayl damp formati
# ---------------------------------------------------------------
def _sections():
    return [{
        "title": "AS Trade", "username": "A_S_trade_1", "chat_id": -100123,
        "messages": [
            {"msg_id": 16193, "date": "2026-10-16 10:34:05", "tag": "",
             "body": "Xop qarela 88-91 sl osa 96-99 activ"},
            {"msg_id": 16194, "date": "2026-10-16 10:35:00", "tag": "[RASM]",
             "body": "caption matni\nikkinchi qator"},
            {"msg_id": 16195, "date": "2026-10-16 10:36:00", "tag": "[VIDEO]",
             "body": ""},
        ],
    }]


def test_dump_file_headers_and_lines():
    meta = {"dumped_at": "17.10.2026 01:00", "channels": 1, "messages": 3, "limit": 1000}
    txt = format_dump_file(_sections(), meta)
    assert txt.startswith("SINO KANAL DAMPI")
    assert "kanallar: 1 | jami xabar: 3 | chegara/kanal: 1000" in txt
    assert "KANAL: AS Trade | @A_S_trade_1 | id=-100123 | xabar: 3" in txt
    assert "[#16193] [2026-10-16 10:34:05] Xop qarela 88-91 sl osa 96-99 activ" in txt
    assert "[#16194] [2026-10-16 10:35:00] [RASM] caption matni" in txt
    assert "  | ikkinchi qator" in txt                     # ko'p qator davomi
    assert "[#16195] [2026-10-16 10:36:00] [VIDEO]" in txt    # media belgisi saqlanadi
    assert txt.endswith("\n")


def test_dump_file_empty_section_safe():
    meta = {"dumped_at": "x", "channels": 1, "messages": 0, "limit": 1000}
    txt = format_dump_file([{"title": "Bo'sh", "username": "", "chat_id": None,
                             "messages": []}], meta)
    assert "KANAL: Bo'sh | @- | id=None | xabar: 0" in txt


# ---------------------------------------------------------------
# (3) INLINE TUGMALAR — yakka qator qolmasligi
# ---------------------------------------------------------------
def _sizes(markup) -> list[int]:
    return [len(row) for row in markup.inline_keyboard]


def test_main_menu_no_lonely_button():
    assert _sizes(KB.main_menu()) == [3, 2, 2, 2]


def test_report_keyboards_paired():
    assert _sizes(KB.report_summary_inline("daily")) == [2]
    assert _sizes(KB.report_full_inline("daily")) == [2]


def test_card_and_result_keyboards_paired():
    assert _sizes(KB.signal_card_kb(5)) == [2]
    assert _sizes(KB.result_short_kb(5)) == [2]
    assert _sizes(KB.result_full_kb(5)) == [2]
    assert _sizes(KB.signal_detail_kb(5)) == [2]
    assert _sizes(KB.menu_controls_kb()) == [2]


def test_misc_keyboards_paired():
    assert _sizes(KB.reports_menu()) == [2, 2]
    assert _sizes(KB.signals_menu()) == [3, 2]
    assert _sizes(KB.paper_menu()) == [2, 2]
    assert _sizes(KB.mode_choice_kb()) == [2, 2]
    assert _sizes(KB.access_menu_kb()) == [2, 2, 2]
    assert _sizes(KB.acc_mode_kb("add")) == [2, 2]
    assert _sizes(KB.bc_confirm_kb()) == [3]


def test_settings_kb_pairs():
    sizes = _sizes(KB.settings_kb(None))
    assert sizes == [2, 2, 1]      # faqat toq 'Menyu' yakka (juftlik yo'q)


# ---------------------------------------------------------------
# (4) VERSIYA
# ---------------------------------------------------------------
def test_version_114():
    from app.services import local_ai
    assert local_ai.__version__ == "SINO-LAI-114"
