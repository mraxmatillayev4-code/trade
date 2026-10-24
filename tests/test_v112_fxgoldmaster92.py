# -*- coding: utf-8 -*-
"""v112: yangi kanal @fxgoldmaster92 (FX GOLD MASTER) formatini o'qish +
kanal qo'shish/o'chirish tasdiq javoblarining "qotishini" oldini olish.

1) Ushbu kanal xabarlari QALIN UNICODE bilan yoziladi
   ("#𝗚𝗢𝗟𝗗 #𝗕𝗨𝗬 𝗡𝗢𝗪 𝟰𝟭𝟴𝟴 ..."). parse_signal endi NFKC bilan
   oddiy matnga tushiradi (avval None qaytarardi).
2) Qat'iy darvoza (channel_real.strict_verdict) FROM/LIMITE ogohlantirishlar,
   "NICE TRADE", "TP x HIT", reklama, READY xabarlarini to'g'ri QAYTA QILADI.
   Replay: dump'dagi 16 ta to'liq signal topiladi (FN=0) va qolgan xabarlar
   signal deb o'tmaydi (FP=0 — yakuniy darvozada).
3) _menu_text_safe / _answer_confirm: kanal qo'shish-o'chirish jarayonlari
   amalni bajaradi lekin tasdiq xabari hech qachon javobsiz qolmaydi.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from app.services.channel_parse import parse_signal, is_close_message  # noqa: E402
from app.services.channel_real import strict_verdict  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sino_fxgoldmaster92_dump.txt"

EXPECTED_SIGNAL_IDS = [4051, 4083, 4096, 4116, 4129, 4147, 4171, 4219,
                       4244, 4256, 4284, 4301, 4331, 4338, 4364, 4372]


# --------------------------------------------------------------------------- #
class TestFxgoldFormat:
    def test_bold_unicode_buy_multiline(self):
        t = ("#𝗚𝗢𝗟𝗗 #𝗕𝗨𝗬  𝗡𝗢𝗪 𝟰𝟭𝟴𝟴\n/𝟰𝟭𝟴𝟱\n\n"
             "𝗧𝗣𝟭  𝟰𝟭𝟵𝟭\n𝗧𝗣𝟮  𝟰𝟭𝟵𝟰\n𝗧𝗣𝟯  𝟰𝟭𝟵𝟳\n𝗧𝗣𝟰  𝟰𝟮𝟬𝟬\n𝗧𝗣𝟱  𝟰𝟮𝟬𝟯\n"
             "𝗧𝗣𝟲  𝟰𝟮𝟬𝟲\n𝗧𝗣𝟳  𝟰𝟮𝟬𝟵\n𝗧𝗣𝟴  𝟰𝟮𝟭𝟮\n𝗧𝗣𝟵  𝟰𝟮𝟭𝟱\n\n\n𝗦𝗟   𝟰𝟭𝟳𝟰")
        r = parse_signal(t)
        assert r is not None, "qalin unicode signal o'qilishi kerak edi"
        assert r.direction == "BUY"
        assert "XAU" in r.symbol
        assert r.entry == 4186.5, f"entry={r.entry} (zona o'rtasi)"
        assert r.sl == 4174.0
        assert r.tps[:3] == [4191.0, 4194.0, 4197.0]
        assert len(r.tps) == 5

    def test_bold_unicode_sell_superscript_tp(self):
        t = ("#𝗚𝗢𝗟𝗗 #𝗦𝗘𝗟𝗟  𝗡𝗢𝗪 𝟰𝟭𝟲𝟬\n/𝟰𝟭𝟲𝟯\n\n"
             "𝗧𝗣¹  𝟰𝟭𝟱𝟳\n𝗧𝗣²  𝟰𝟭𝟱𝟰\n𝗧𝗣³  𝟰𝟭𝟱𝟭\n𝗧𝗣⁴  𝟰𝟭𝟰𝟴\n𝗧𝗣⁵  𝟰𝟭𝟰𝟱\n\n\n𝗦𝗟   𝟰𝟭𝟳𝟰")
        r = parse_signal(t)
        assert r is not None
        assert r.direction == "SELL"
        assert r.entry == 4161.5
        assert r.sl == 4174.0
        assert r.tp == 4157.0
        assert len(r.tps) == 5

    def test_range_same_line(self):
        t = ("#𝗚𝗢𝗟𝗗 #𝗕𝗨𝗬  𝗡𝗢𝗪 𝟰𝟭𝟳𝟲/𝟰𝟭𝟳𝟯\n\n\n"
             "𝗧𝗣¹  𝟰𝟭𝟳𝟵\n𝗧𝗣²  𝟰𝟭𝟴𝟮\n𝗧𝗣³  𝟰𝟭𝟴𝟱\n𝗧𝗣⁴  𝟰𝟭𝟴𝟴\n𝗧𝗣⁵  𝟰𝟭𝟵𝟭\n\n\n𝗦𝗟   𝟰𝟭𝟲𝟭")
        r = parse_signal(t)
        assert r is not None
        assert r.entry == 4174.5
        assert r.sl == 4161.0

    def test_close_all_trades_bold(self):
        assert is_close_message("𝗚𝘂𝘆𝘀 𝗖𝗹𝗼𝘀𝗲 𝗔𝗹𝗹 𝗧𝗿𝗮𝗱𝗲𝘀 𝗡𝗼𝘄") is True


# --------------------------------------------------------------------------- #
class TestStrictGateNoFalsePositives:
    """Soddagina-gate (parse_signal) follow-up'larni o'tkazishi mumkin —
    faqat og'ir darvoza (strict_verdict) qaror qilib qolish kerak."""

    @pytest.mark.parametrize("name,txt", [
        ("FROM", "𝗚𝗢𝗟𝗗 𝗕𝗨𝗬 𝗙𝗥𝗢𝗠 𝟰𝟭𝟴𝟴"),
        ("LIMITE", "𝗚𝗢𝗟𝗗 𝗦𝗘𝗟𝗟 𝗟𝗜𝗠𝗜𝗧𝗘 𝟰𝟭𝟯𝟯"),
        ("NICE TRADE", "#𝗫𝗔𝗨𝗨𝗦𝗗_#𝗕𝗨𝗬\n\n𝗡𝗜𝗖𝗘 𝗧𝗥𝗔𝗗𝗘"),
        ("TP HIT", "#𝗫𝗔𝗨𝗨𝗦𝗗_#𝗕𝗨𝗬\n\n𝗧𝗣 𝟭 𝗛𝗜𝗧 𝟯𝟬+ 𝗣𝗜𝗣𝗦 𝗣𝗥𝗢𝗙𝗜𝗧 𝗕𝗢𝗶𝗸"),
        ("ALL TP DONE", "𝗫𝗔𝗨𝗨𝗦𝗗 𝗕𝗨𝗬\n\n𝗔𝗹𝗹 𝗧𝗣 𝗗𝗢𝗠𝗘 𝟭𝟱𝟬+𝗣𝗜𝗣𝗦 𝗣𝗥𝗢𝗙𝗜𝗧 𝗗𝗢𝗡𝗘"),
        ("READY", "𝗥𝗘𝗔𝗗𝗬 𝗙𝗢𝗥 𝗫𝗔𝗨𝗨𝗦𝗗 𝗣𝗥𝗘𝗠𝗜𝗨𝗠 𝗦𝗜𝗚𝗡𝗔𝗟𝗦"),
        ("reklama", "Do You Have 200$\nDaily Profit 550$\nContact @Ghalib_Fx4"),
        ("wow", "𝗪𝗼𝗪"),
        ("best of luck", "𝗚𝘂𝘆𝘀 𝗕𝗲𝘀𝘁 𝗢𝗳 𝗟𝘂𝗰𝗸🤞🍀"),
    ])
    def test_not_signal(self, name, txt):
        v = strict_verdict(txt)
        assert v.get("verdict") == "EMAS", f"{name} signal deb topildi: {v}"

    def test_full_signal_accepted(self):
        t = ("#𝗚𝗢𝗟𝗗 #𝗕𝗨𝗬  𝗡𝗢𝗪 𝟰𝟭𝟴𝟴\n/𝟰𝟭𝟴𝟱\n\n"
             "𝗧𝗣𝟭  𝟰𝟭𝟵𝟭\n𝗧𝗣𝟮  𝟰𝟭𝟵𝟰\n𝗧𝗣𝟯  𝟰𝟭𝟵𝟳\n𝗧𝗣𝟰  𝟰𝟮𝟬𝟬\n𝗧𝗣𝟱  𝟰𝟮𝟬𝟯\n"
             "𝗧𝗣𝟲  𝟰𝟮𝟬𝟲\n𝗧𝗣𝟳  𝟰𝟮𝟬𝟵\n𝗧𝗣𝟴  𝟰𝟮𝟭𝟮\n𝗧𝗣𝟵  𝟰𝟮𝟭𝟱\n\n\n𝗦𝗟   𝟰𝟭𝟳𝟰")
        v = strict_verdict(t)
        assert v.get("verdict") == "SIGNAL"
        assert v.get("direction") == "BUY"
        assert len(v.get("tps") or []) == 9


# --------------------------------------------------------------------------- #
class TestReplayDump:
    @staticmethod
    def _messages():
        raw = FIXTURE.read_text(encoding="utf-8")
        parts = re.split(r"\n-{5,}\n", raw)
        out = []
        for p in parts:
            m = re.search(r"^\[(\d+)\] ", p, re.M)
            if not m:
                continue
            tm = re.search(r"\[MATN\] (.*)", p, re.S)
            if not tm:
                continue
            text = re.split(r"\n\[RASM MATNI\]", tm.group(1))[0]
            out.append((int(m.group(1)), text))
        return out

    def test_dump_fixture_exists(self):
        assert FIXTURE.exists()

    def test_replay_16_signals_fn0(self):
        msgs = self._messages()
        strict_signal = set()
        for mid, txt in msgs:
            if strict_verdict(txt).get("verdict") == "SIGNAL":
                strict_signal.add(mid)
        missing = [x for x in EXPECTED_SIGNAL_IDS if x not in strict_signal]
        assert not missing, f"qat'iy darvoza signal topa olmadi (FN): {missing}"

    def test_replay_fp0_reja_darajasida(self):
        """Yakuniy darvoza: 16 to'liq — reja bilan (SL+TP); ogohlantirish
        xabarlari esa faqat 'daraja' (rejasiz — SL va TP bo'sh) bo'ladi va
        v101 fragment-buffer ularni 45s kutib qoladi (plan kelganda bekor
        qilinadi). Follow-up/reklama/READY esa umuman SIGNAL emas."""
        msgs = self._messages()
        planned, planless, weird = [], [], []
        for mid, txt in msgs:
            v = strict_verdict(txt)
            if v.get("verdict") != "SIGNAL":
                continue
            if v.get("sl") is not None and (v.get("tps") or []):
                planned.append(mid)
            else:
                (planless if mid not in EXPECTED_SIGNAL_IDS else weird).append(mid)
        assert not weird, f"plan-li SIGNAL xabarlar kutilmagan yerda: {weird}"
        missing = [x for x in EXPECTED_SIGNAL_IDS if x not in planned]
        assert not missing, f"plan bilan topilmagan (FN): {missing}"
        bad_followup = [mid for mid, txt in msgs
                        if mid not in EXPECTED_SIGNAL_IDS
                        and mid not in planless
                        and strict_verdict(txt).get("verdict") == "SIGNAL"
                        and (strict_verdict(txt).get("sl") is not None
                             or strict_verdict(txt).get("tps"))]
        assert not bad_followup, f"follow-up reja bilan signal bo'ldi (FP): {bad_followup}"

    def test_parse_gate_catches_signals(self):
        """Yengil gate (parse_signal) ham 16 signalni ko'rishi kerak (NFKC)."""
        msgs = dict(self._messages())
        for mid in EXPECTED_SIGNAL_IDS:
            r = parse_signal(msgs.get(mid, ""))
            assert r is not None and r.tps, f"[{mid}] parse_signal o'qimadi"


# --------------------------------------------------------------------------- #
class TestAddRemoveNoSilence:
    @staticmethod
    def _load():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "channels_mod_v112", str(ROOT / "app" / "bot" / "handlers" / "channels.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    @pytest.mark.asyncio
    async def test_menu_text_safe_never_raises(self):
        ch = self._load()

        async def _boom(session, is_admin):
            raise RuntimeError("PGDialect xatosi / jadval yo'q")

        class _AC:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *a):
                return False

        async def _no_channels(session):
            return [{"username": "fxgoldmaster92", "chat_id": None,
                     "title": "", "kind": "public"}]

        ch._menu_text = _boom
        ch.list_channels = _no_channels
        txt = await ch._menu_text_safe(object(), True)
        assert "SIGNAL KANALLARI" in txt
        assert "fxgoldmaster92" in txt

    @pytest.mark.asyncio
    async def test_answer_confirm_falls_back_to_plain(self):
        ch = self._load()

        class _Msg:
            def __init__(self):
                self.sent = []

            async def answer(self, text, **kw):
                if kw.get("parse_mode") == "HTML":
                    raise RuntimeError("can't parse entities")
                self.sent.append(text)

        m = _Msg()
        await ch._answer_confirm(m, "✅ <b>Kanal ulandi</b> - test <i>izoh</i>")
        assert m.sent and m.sent[0].startswith("✅ Kanal ulandi")
        assert "<b>" not in m.sent[0]


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
