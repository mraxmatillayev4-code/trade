# -*- coding: utf-8 -*-
"""v111: kalkulyator «Bekor qilish» va «Kanallar» menyusi — xatoliklarni
tog'irlaydigan regressiya testlari.

V111 da tuzatilgan xatoliklar:
1) aiogram'da handlerlar DEKLARATSIYA tartibida tekshiriladi. «✖️ Bekor qilish»
   matni CalcState.lot holatga tegishli BARCHA matnlarni ushlaydigan handler
   (calc_got_lot) tomonidan yutib yuborilib, «Lot xato» deb o'qilardi.
   Endi: (a) calc_cancel handler BIRINCHI deklaratsiya qilingan,
         (b) calc_got_lot/calc_got_pips ichida ham bekor-event himoyasi bor.
2) «Kanallar» menyusi HTML/DB xatosida butunlay javobsiz qolardi —
   endi HAR QANDAY xatolikda oddiy matnli menyu qaytariladi.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


def _load(modname: str, path: str):
    spec = importlib.util.spec_from_file_location(modname, str(ROOT / path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


calc = _load("calc_mod_v111", "app/bot/handlers/calc.py")
channels = _load("channels_mod_v111", "app/bot/handlers/channels.py")
common = _load("common_mod_v111", "app/bot/handlers/common.py")
kb = _load("kb_mod_v111", "app/bot/keyboards.py")

from aiogram.dispatcher.event.bases import SkipHandler  # noqa: E402


# --------------------------------------------------------------------------- #
class _FakeUser:
    def __init__(self, uid=1):
        self.id = uid
        self.is_bot = False
        self.username = "test"
        self.full_name = "Test"


class _FakeBot:
    async def send_message(self, *a, **kw):
        return None


class _FakeMessage:
    def __init__(self, text="", uid=1):
        self.text = text
        self.from_user = _FakeUser(uid)
        self.answers: list = []
        self.bot = _FakeBot()

    async def answer(self, text, **kw):
        self.answers.append((text, kw))
        return self


class _FakeState:
    def __init__(self):
        self.ops: list = []
        self.data: dict = {}

    async def set_state(self, s):
        self.ops.append(("set", s))

    async def update_data(self, **kw):
        self.data.update(kw)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.ops.append(("clear", None))


# --------------------------------------------------------------------------- #
class TestCalcCancel:
    def test_cancel_text_variants(self):
        f = calc._is_cancel_text
        assert f("✖️ Bekor qilish")
        assert f("bekor qilish")
        assert f("BEKOR QILISH")
        assert f("Bekor")
        assert not f("0.01")
        assert not f("")
        assert not f(None)

    def test_router_order_cancel_first(self):
        names = [getattr(h.callback, "__name__", "") for h in calc.router.message.handlers]
        # bekorish handlerlari catch-all state handlerlaridan OLDIN bo'lishi shart
        first_cancel = names.index("calc_cancel")
        first_lot = names.index("calc_got_lot")
        first_pips = names.index("calc_got_pips")
        assert first_cancel < first_lot, "calc_cancel lot catch-all dan oldin bo'lsin"
        assert first_cancel < first_pips, "calc_cancel pips catch-all dan oldin bo'lsin"

    @pytest.mark.asyncio
    async def test_bekor_at_lot_step_cancels(self, monkeypatch):
        monkeypatch.setattr(calc, "is_admin", lambda uid: True)
        st = _FakeState()
        msg = _FakeMessage("✖️ Bekor qilish")
        await calc.calc_got_lot(msg, st)
        assert ("clear", None) in st.ops, "bekor bosilganda state tozalanadi"
        txt = " ".join(a[0] for a in msg.answers)
        assert "Kalkulyator yopildi" in txt, f"javoblar: {txt!r}"
        assert "Lot xato" not in txt

    @pytest.mark.asyncio
    async def test_bekor_at_pips_step_cancels(self, monkeypatch):
        monkeypatch.setattr(calc, "is_admin", lambda uid: True)
        st = _FakeState()
        msg = _FakeMessage("bekor qilish")
        await calc.calc_got_pips(msg, st)
        assert ("clear", None) in st.ops
        txt = " ".join(a[0] for a in msg.answers)
        assert "Kalkulyator yopildi" in txt

    @pytest.mark.asyncio
    async def test_lot_number_still_works(self, monkeypatch):
        monkeypatch.setattr(calc, "is_admin", lambda uid: True)
        st = _FakeState()
        msg = _FakeMessage("0.01")
        await calc.calc_got_lot(msg, st)
        assert st.data.get("lot") == "0.01", f"state: {st.data}"
        assert any(("set", calc.CalcState.pips) == op for op in st.ops)


# --------------------------------------------------------------------------- #
class TestChannelsMenuGuard:
    @staticmethod
    def _patch_admin(monkeypatch, ok=True):
        monkeypatch.setattr(channels, "_is_admin", lambda uid: ok)

    @pytest.mark.asyncio
    async def test_menu_fallback_when_text_raises(self, monkeypatch):
        """_menu_text qulasa ham menyu HECH QACHON jim qolmaydi."""
        self._patch_admin(monkeypatch)

        class _DB:
            pass

        class _AC:
            async def __aenter__(self):
                return _DB()

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(channels, "async_session_factory", lambda: _AC())

        async def _boom(session, is_admin):
            raise RuntimeError("HTML buzilgan")

        async def _no_channels(session):
            return []

        monkeypatch.setattr(channels, "_menu_text", _boom)
        monkeypatch.setattr(channels, "list_channels", _no_channels)

        msg = _FakeMessage("📡 Kanallar")
        st = _FakeState()
        await channels.channels_menu(msg, st)
        assert msg.answers, "menyu javobi yo'q edi — xato!"
        txt, kw = msg.answers[0]
        assert "SIGNAL KANALLARI" in txt
        # v112: fallback endi _menu_text_safe orqali ham kelsa bo'ladi
        assert ("Ulangan: 0/" in txt) or ("statistika vaqtincha" in txt)

    @pytest.mark.asyncio
    async def test_menu_non_admin_gets_notice(self, monkeypatch):
        self._patch_admin(monkeypatch, False)
        msg = _FakeMessage("📡 Kanallar", uid=777)
        st = _FakeState()
        await channels.channels_menu(msg, st)
        assert msg.answers and "faqat admin" in msg.answers[0][0]

    def test_menu_handler_registered(self):
        names = {getattr(h.callback, "__name__", "") for h in channels.router.message.handlers}
        assert "channels_menu" in names


# --------------------------------------------------------------------------- #
class TestMenuSwallowGuard:
    def test_is_menu_text_known_buttons(self):
        f = kb.is_menu_text
        assert f("📡 Kanallar")
        assert f("🔐 Access (ro'yxat)")
        assert f("✖️ Bekor qilish")
        assert f("🧮 Kalkulyator")
        assert f("⬅️ Orqaga")
        assert not f("oddiy matn")
        assert not f("0.01")
        assert not f("")
        assert not f(None)

    @pytest.mark.asyncio
    async def test_menu_exit_raises_skip_and_clears(self):
        st = _FakeState()
        msg = _FakeMessage("📡 Kanallar")
        with pytest.raises(SkipHandler):
            await common._menu_exit(msg, st)
        assert ("clear", None) in st.ops

    @pytest.mark.asyncio
    async def test_menu_exit_ignores_normal_text(self):
        st = _FakeState()
        msg = _FakeMessage("123456789")
        await common._menu_exit(msg, st)   # SkipHandler tashlamaydi
        assert not st.ops


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
