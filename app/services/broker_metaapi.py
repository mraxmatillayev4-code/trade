# -*- coding: utf-8 -*-
"""MetaAPI bulut integratsiyasi v119 — MT5 savdosi FOYDALANUVCHI KOMPYUTERISIZ.

metaapi.cloud xizmati MT5 akkauntini ULARNING BULUTida yetib uradi:
kompyuteringiz o'chiq bo'lsa ham bot signallarni aniq ochadi-yopadi.
FREE tier: 1 MT akkauntiga API bepul. Ko'proq akkaunt = pullik.

TO'G'RIDAN-TO'G'RI IMPORT QILMAYMIZ: paket yo'q bo'lganda ham bot yiqilmasin
(metaapi-cloud-sdk requirements.txt da, Render build vaqtida o'rnatiladi).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

SDK_TIMEOUT = 25.0  # deploy/ulanish kutish vaqti (sekund)


def _sdk():
    """Lazy import — Render build oldidan lokal testlarda paket bo'lmasligi mumkin."""
    try:
        from metaapi_cloud_sdk import MetaApi  # type: ignore
        return MetaApi
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "metaapi-cloud-sdk o'rnatilmagan: pip install metaapi-cloud-sdk"
        ) from exc


def _sym_translate(sym: str) -> str:
    """Botning ichki simvolini broker simvoliga o'girish (XAUUSDT -> XAUUSD)."""
    s = (sym or "").upper().strip()
    if s in ("XAU", "GOLD", "XAUUSDT", "XAUUSD"):
        return "XAUUSD"
    return s or "XAUUSD"


async def create_metaapi_account(api_token: str, login: str, password: str,
                                 server: str, name: str = "SINO MT5"
                                 ) -> tuple[str, str]:
    """v125: MT5 akkauntni BOT O'ZI MetaApi'da yaratadi — foydalanuvchi
    saytda akkaunt ochishi yoki Account ID qidirishi SHART EMAS.

    Kerak faqat: API token (saytdan 2 daqiqada olinadi).
    Qaytaradi: (account_id, "") yoki ("", xato_matni).
    """
    MetaApi = _sdk()
    api = None
    try:
        api = MetaApi(api_token)
        acct = await api.metatrader_account_api.create_account({
            "name": name[:32],
            "type": "cloud-g2",
            "login": str(login or "").strip(),
            "password": str(password or ""),
            "server": str(server or "").strip(),
            "magic": 0,
            "application": "MetaApi",
        })
        aid = str(getattr(acct, "id", "") or "")
        if aid:
            return aid, ""
        return "", "create_account bo'sh javob qaytardi"
    except Exception as exc:  # noqa: BLE001
        return "", str(exc)[:160]
    finally:
        try:
            if api is not None:
                await api.close()
        except Exception:  # noqa: BLE001
            pass


class MetaApiBridge:
    """MetaApi managmenet + RPC ulanishini boshqaruvchi.

    - connect(): akkauntni olib, kerak bo'lsa deploy, RPC trade ulanishini ochadi.
    - open_market(): BUY/SELL market order (SL/TP bilan yuboriladi).
    - close_by_comment(): 'SINO' izohli pozitsiyani lot bo'yicha topib yopadi.
    """

    def __init__(self, api_token: str, account_id: str, timeout: float = SDK_TIMEOUT):
        self.api_token = api_token
        self.account_id = account_id
        self.timeout = float(timeout or SDK_TIMEOUT)
        self._api = None
        self._account = None
        self._rpc = None          # RpcMetaApiConnectionInstance
        self._synced = False

    # ----------------------------------------------------------- ulanish
    async def connect(self) -> tuple[bool, str]:
        """Akkauntni deploy qilib, RPC ulanishini ochish. (ok, xato)."""
        MetaApi = _sdk()
        try:
            self._api = MetaApi(self.api_token)
        except Exception as exc:  # noqa: BLE001
            return False, f"API token xatosi: {exc}"
        try:
            self._account = await self._api.metatrader_account_api.get_account(self.account_id)
        except Exception as exc:  # noqa: BLE001
            await self._shutdown()
            return False, f"account_id xato yoki akkaunt topilmadi: {exc}"
        try:
            if getattr(self._account, "state", None) != "DEPLOYED":
                await self._account.deploy()
            await asyncio.wait_for(self._account.wait_deployed(), timeout=self.timeout * 6)
            await asyncio.wait_for(self._account.wait_connected(), timeout=self.timeout * 6)
        except Exception as exc:  # noqa: BLE001
            await self._shutdown()
            return False, f"deploy/ulanish kutishda xatolik: {exc}"
        try:
            self._rpc = self._account.get_rpc_connection()
            await self._rpc.connect()
            await asyncio.wait_for(self._rpc.wait_synchronized(self.timeout), timeout=self.timeout + 5)
            self._synced = True
        except Exception as exc:  # noqa: BLE001
            await self._shutdown()
            return False, f"RPC sinxronizatsiya: {exc}"
        logger.info("[METAAPI] RPC ulanish tayyor: account=%s", self.account_id)
        return True, ""

    async def _shutdown(self) -> None:
        try:
            if self._rpc:
                await self._rpc.close()
        except Exception:  # noqa: BLE001
            pass
        self._rpc = None
        self._synced = False
        try:
            if self._api:
                await self._api.close()
        except Exception:  # noqa: BLE001
            pass
        self._api = None
        self._account = None

    async def close(self) -> None:
        """Barcha ulanishlarni chiqarish."""
        await self._shutdown()
        logger.debug("[METAAPI] yopildi")

    async def ensure_live(self) -> None:
        """Sinxron holatda emas bo'lsa qayta ulanish."""
        if self._rpc and self._synced:
            try:
                alive = await self._rpc.is_synchronized()
            except Exception:  # noqa: BLE001
                alive = False
            if alive:
                return
        await self._shutdown()
        await asyncio.sleep(0.4)
        ok, err = await self.connect()
        if not ok:
            raise RuntimeError(f"Qayta ulanib bo'lmadi: {err}")

    # ---------------------------------------------------- o'zlashtirish
    async def account_info(self) -> dict:
        """Balans/equity/valyuta/server ma'lumoti (kata allaqachon sync bo'lgan)."""
        await self.ensure_live()
        info = await self._rpc.get_account_information()
        return {
            "balance": float(info.get("balance") or 0.0),
            "equity": float(info.get("equity") or 0.0),
            "currency": str(info.get("currency") or ""),
            "server": str(info.get("server") or ""),
            "login": str(info.get("login") or ""),
            "type": str(info.get("type") or ""),
        }

    async def positions(self) -> list[dict]:
        await self.ensure_live()
        raw = await self._rpc.get_positions()
        out: list[dict] = []
        for p in raw or []:
            out.append({
                "id": str(p.get("id") or ""),
                "symbol": str(p.get("symbol") or ""),
                "type": str(p.get("type") or ""),
                "volume": float(p.get("volume") or 0.0),
                "comment": str(p.get("comment") or ""),
                "profit": float(p.get("profit") or 0.0),
                "openPrice": float(p.get("openPrice") or 0.0),
            })
        return out

    # ----------------------------------------------------------- savdo
    async def open_market(self, symbol: str, side: str, lot: float,
                          sl: float = 0.0, tp: float = 0.0,
                          comment: str = "SINO") -> dict:
        """Market order ochish SL/TP bilan. Ticket -> orderId/positionId."""
        await self.ensure_live()
        sym = _sym_translate(symbol)
        volume = max(0.01, float(lot or 0.01))
        options: dict[str, Any] = {}
        if comment:
            options["comment"] = str(comment)[:31]
        sl_val = float(sl or 0.0)
        tp_val = float(tp or 0.0)
        sl_arg = sl_val if sl_val > 0 else None
        tp_arg = tp_val if tp_val > 0 else None
        side_u = (side or "BUY").upper()
        try:
            if side_u == "BUY":
                resp = await self._rpc.create_market_buy_order(sym, volume, sl_arg, tp_arg, options)
            else:
                resp = await self._rpc.create_market_sell_order(sym, volume, sl_arg, tp_arg, options)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:100], "flat_error": None, "ret_hint": None}
        code = int(resp.get("numericCode") or 0)
        ok = code in (10008, 10009)
        ticket = None
        for k in ("orderId", "positionId"):
            v = resp.get(k)
            if v:
                try:
                    ticket = int(v)
                    break
                except (TypeError, ValueError):
                    pass
        if ok and ticket:
            return {"ok": True, "ticket": ticket, "code": code,
                    "message": str(resp.get("message") or "")[:80]}
        return {"ok": False, "error": f"{code}: {str(resp.get('message') or '')[:80]}",
                "code": code}

    def _pick_position(self, poss: list, sym: str, comment_prefix: str,
                       target_lot: float):
        """Pozitsiya tanlash (v125): avval ANIQ izoh mosligi (SINO Lot2),
        keyin lot o'lchamiga eng yaqini. Ikkala lot bir xil hajmda bo'lganida
        Lot1/Lot2 ni izoh bo'yicha ajratish shart."""
        best = None
        for p in poss or []:
            if str(p.get("symbol") or "") != sym:
                continue
            c = str(p.get("comment") or "")
            if not c.startswith(comment_prefix[:4]):
                continue
            # ANIQ izoh mosligi ("SINO Lot2") — eng yuqori ustunlik
            if comment_prefix != "SINO" and c.startswith(comment_prefix):
                return p
            diff = abs(float(p.get("volume") or 0.0) - target_lot)
            if target_lot <= 0.0:
                return p
            if best is None or diff < best[1]:
                best = (p, diff)
        return best[0] if best is not None else None

    async def close_by_comment(self, symbol: str, comment_prefix: str = "SINO",
                               lot: float = 0.0, price: float = 0.0) -> dict:
        """SINO izohli ochiq pozitsiyalardan lot o'lchamiga eng mosini yopish."""
        await self.ensure_live()
        sym = _sym_translate(symbol)
        poss = await self._rpc.get_positions()
        pos = self._pick_position(poss, sym, str(comment_prefix or "SINO"),
                                  float(lot or 0.0))
        if pos is None:
            return {"ok": False, "error": "SINO izohli pozitsiya topilmadi"}
        pos_id = str(pos.get("id") or "")
        try:
            resp = await self._rpc.close_position(pos_id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:120]}
        code = int(resp.get("numericCode") or 0)
        if code in (10008, 10009):
            return {"ok": True, "closed": 1, "positionId": pos_id}
        return {"ok": False, "error": f"{code}: {str(resp.get('message') or '')[:80]}"}

    async def modify_sl(self, symbol: str, comment_prefix: str = "SINO",
                        lot: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> dict:
        """v125: pozitsiyaning STOPLOSSINI o'zgartirish (masalan Lot2 SL → TP1
        himoyasi). TP berilmasa — mavjud TP o'zgarmasdan qoladi."""
        await self.ensure_live()
        sym = _sym_translate(symbol)
        poss = await self._rpc.get_positions()
        pos = self._pick_position(poss, sym, str(comment_prefix or "SINO"),
                                  float(lot or 0.0))
        if pos is None:
            return {"ok": False, "error": "pozitsiya topilmadi"}
        pos_id = str(pos.get("id") or "")
        new_sl = float(sl or 0.0)
        cur_tp = float(pos.get("takeProfit") or 0.0)
        new_tp = float(tp or 0.0) or cur_tp
        if new_sl <= 0.0:
            return {"ok": False, "error": "yangi SL nol bo'lishi mumkin emas"}
        try:
            resp = await self._rpc.modify_position(pos_id, stop_loss=new_sl,
                                                   take_profit=(new_tp or None))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:120]}
        code = int(resp.get("numericCode") or 0)
        if code in (10008, 10009):
            return {"ok": True, "positionId": pos_id, "sl": new_sl, "tp": new_tp}
        return {"ok": False, "error": f"{code}: {str(resp.get('message') or '')[:80]}"}
