"""v128: BEK FXX 'buy now 4062-4057' narx 4065 da bo'lganda darhol kirish testi."""
import pytest
from app.services import channel_inbox as CI
from app.services.channel_parse import parse_signal
from types import SimpleNamespace as NS

class _FakeSession:
    async def commit(self): pass

def _sig_bek():
    return NS(
        id=999, symbol="XAUUSDT", direction="BUY",
        quality_mode="CHANNEL", entry=None,
        entry_mode=None, entry_status=None,
        entry_low=None, entry_high=None,
        entry_expires_at=None, entry_note=None,
        sl=4055.0, tp1=4070.0,
        raw_text="Xauusd buy now 4062-4057\nSl 4055.00\nTp 4070"
    )

@pytest.mark.asyncio
async def test_bek_fxx_buy_now_enters_immediately(monkeypatch):
    """BEK FXX: 'buy now 4062-4057', joriy narx 4065.92 (zonaga yaqin) —
    kutib o'tirmaydi, darhol zona o'rtasidan (4059.50) kiradi!"""
    text = "Xauusd buy now 4062-4057\nSl 4055.00\nTp 4070"
    parsed = parse_signal(text)
    assert parsed.direction == "BUY"
    assert parsed.zone_low == 4057.0
    assert parsed.zone_high == 4062.0

    monkeypatch.setattr(CI, "_last_px", lambda s: 4065.92)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", lambda s: None)

    sig = _sig_bek()
    st = await CI._apply_entry_plan(_FakeSession(), sig, parsed, NS(channel_expiry_minutes=240))
    assert st == "filled", "BEK FXX 'buy now' signali darhol ochilishi shart!"
    assert sig.entry_status == "FILLED"
    assert sig.entry == 4059.50
    assert "zona o'rtasidan kirdi" in sig.entry_note
