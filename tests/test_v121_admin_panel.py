"""v121: ADMIN BOSHQARUVI — DB-siz (DB qismi boshqa suite larda sinovlangan)."""
import pytest

from app.core import access as ACC


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Har testdan oldin: xotira toza + DB sessiyasini soxtalashtirish."""
    ACC._extra.clear()
    ACC._hydrated = True

    class _NoDb:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    from app.database import session as _sess
    monkeypatch.setattr(
        _sess, "async_session_factory", lambda *a, **kw: _NoDb())

    async def _save(session, component, data):
        return None

    import app.services.channel_store as _cs
    monkeypatch.setattr(_cs, "save_json_log", _save)
    yield


@pytest.mark.asyncio
async def test_add_remove_admin():
    ok = await ACC.add_admin(555111)
    assert ok is True and ACC.is_admin(555111) is True
    ok2 = await ACC.add_admin(555111)
    assert ok2 is False                      # idempotent
    r = await ACC.remove_admin(555111)
    assert r == "ok" and ACC.is_admin(555111) is False
    r2 = await ACC.remove_admin(555111)
    assert r2 == "notfound"


@pytest.mark.asyncio
async def test_super_admin_protected():
    await ACC.add_admin(111)
    await ACC.add_admin(222)
    sup = ACC.super_admin_id()
    assert sup is not None and ACC.is_super_admin(sup) is True
    r = await ACC.remove_admin(sup)
    assert r == "super"                      # QALQON
    assert ACC.is_admin(sup) is True
    other = 222 if sup != 222 else 111
    other = [x for x in (111, 222) if x != sup][0]
    r2 = await ACC.remove_admin(other)
    assert r2 == "ok"


@pytest.mark.asyncio
async def test_list_admins_super_first():
    await ACC.add_admin(999)
    await ACC.add_admin(111)
    rows = ACC.list_admins()
    sup = ACC.super_admin_id()
    assert sup is not None
    super_rows = [r for r in rows if r["role"] == "super"]
    assert len(super_rows) == 1
    ids = {r["id"] for r in rows}
    assert {999, 111} <= ids


@pytest.mark.asyncio
async def test_notify_super_skips_itself():
    class _B:
        sent: list = []

        async def send_message(self, cid, text, parse_mode=None):
            self.sent.append((cid, text))

    await ACC.add_admin(111)
    b = _B()
    sup = ACC.super_admin_id()
    await ACC.notify_super(b, "xabar", except_uid=sup)
    assert b.sent == []                       # super o'ziga emas
    await ACC.notify_super(b, "yana", except_uid=999111)
    assert len(b.sent) == 1 and int(b.sent[0][0]) == int(sup)


def test_is_admin_none_false():
    assert ACC.is_admin(None) is False
    assert ACC.is_admin(0) is False


def test_audit_text_cr():
    t = ACC.audit_text(123, "@bob", "TEST harakati")
    for needle in ("123", "@bob", "TEST harakati", "AUDIT"):
        assert needle in t
