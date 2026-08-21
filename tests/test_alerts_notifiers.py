import requests

from fpl_agent.alerts.engine import (
    Alert,
    CompositeNotifier,
    DiscordNotifier,
    TelegramNotifier,
    WindowsToastNotifier,
    _build_toast_script,
    configured_notifiers,
)

_ALERT = Alert(
    change_event_id=1, event_type="status_change", entity="player", entity_id=1,
    severity="HIGH", old_value="a", new_value="i", detected_at="t0",
)

_SECRET_TOKEN = "123456:SECRET_BOT_TOKEN"
_SECRET_WEBHOOK = "https://discord.com/api/webhooks/123/SECRET_WEBHOOK_TOKEN"


def test_telegram_notifier_posts_the_alert_text(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        resp = requests.Response()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("fpl_agent.alerts.engine.requests.post", fake_post)
    TelegramNotifier(_SECRET_TOKEN, "chat123").send(_ALERT)

    assert len(calls) == 1
    url, payload = calls[0]
    assert url == f"https://api.telegram.org/bot{_SECRET_TOKEN}/sendMessage"
    assert payload["chat_id"] == "chat123"
    assert "HIGH" in payload["text"]
    assert "player#1" in payload["text"]


def test_discord_notifier_posts_the_alert_text(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        resp = requests.Response()
        resp.status_code = 204
        return resp

    monkeypatch.setattr("fpl_agent.alerts.engine.requests.post", fake_post)
    DiscordNotifier(_SECRET_WEBHOOK).send(_ALERT)

    assert len(calls) == 1
    url, payload = calls[0]
    assert url == _SECRET_WEBHOOK
    assert "HIGH" in payload["content"]
    assert "player#1" in payload["content"]


def test_telegram_delivery_failure_never_crashes_and_never_leaks_the_token(monkeypatch, db_conn):
    """Same leak class already fixed in ingestion/odds_live_source.py: the bot
    token lives in the request URL, and requests' own exception __str__()
    embeds the full URL - the persisted source_health.last_error and the
    printed warning must never contain it."""
    def fake_post(url, json, timeout):
        raise requests.ConnectionError(f"Connection refused for url: {url}")

    monkeypatch.setattr("fpl_agent.alerts.engine.requests.post", fake_post)

    notifier = TelegramNotifier(_SECRET_TOKEN, "chat123", conn=db_conn)
    notifier.send(_ALERT)  # must not raise

    health = db_conn.execute("SELECT * FROM source_health WHERE source_name='telegram_alerts'").fetchone()
    assert health is not None
    assert health["failure_count"] >= 1
    assert _SECRET_TOKEN not in (health["last_error"] or "")


def test_discord_delivery_failure_never_crashes_and_never_leaks_the_webhook_url(monkeypatch, db_conn):
    def fake_post(url, json, timeout):
        raise requests.ConnectionError(f"Connection refused for url: {url}")

    monkeypatch.setattr("fpl_agent.alerts.engine.requests.post", fake_post)

    notifier = DiscordNotifier(_SECRET_WEBHOOK, conn=db_conn)
    notifier.send(_ALERT)  # must not raise

    health = db_conn.execute("SELECT * FROM source_health WHERE source_name='discord_alerts'").fetchone()
    assert health is not None
    assert health["failure_count"] >= 1
    assert _SECRET_WEBHOOK not in (health["last_error"] or "")


def test_composite_notifier_fans_out_to_every_channel():
    sent_a, sent_b = [], []

    class RecA:
        def send(self, alert):
            sent_a.append(alert)

    class RecB:
        def send(self, alert):
            sent_b.append(alert)

    CompositeNotifier([RecA(), RecB()]).send(_ALERT)

    assert sent_a == [_ALERT]
    assert sent_b == [_ALERT]


def test_composite_notifier_one_channel_failing_does_not_block_the_others():
    sent = []

    class Failing:
        def send(self, alert):
            raise RuntimeError("boom")

    class Working:
        def send(self, alert):
            sent.append(alert)

    # CompositeNotifier itself doesn't swallow exceptions - each real network
    # notifier (Telegram/Discord) is responsible for catching its own
    # failure internally (see the tests above), which is what actually
    # prevents one down channel from blocking the others in practice.
    import pytest
    with pytest.raises(RuntimeError):
        CompositeNotifier([Failing(), Working()]).send(_ALERT)


def test_configured_notifiers_always_includes_terminal_and_adds_configured_channels(monkeypatch, db_conn):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _SECRET_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat123")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    composite = configured_notifiers(db_conn)

    kinds = [type(n).__name__ for n in composite._notifiers]
    assert "TerminalNotifier" in kinds
    assert "TelegramNotifier" in kinds
    assert "DiscordNotifier" not in kinds  # not configured


def test_configured_notifiers_is_terminal_and_toast_only_with_no_env_configured(monkeypatch, db_conn):
    """2026-08-21: WindowsToastNotifier is now the standing default push
    channel (no config needed, unlike Telegram/Discord) - real per-platform
    expectation, not a hardcoded "always these two", so this pins the
    platform-conditional behavior explicitly rather than just asserting a
    fixed list."""
    import sys

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    composite = configured_notifiers(db_conn)

    kinds = [type(n).__name__ for n in composite._notifiers]
    expected = ["TerminalNotifier", "WindowsToastNotifier"] if sys.platform == "win32" else ["TerminalNotifier"]
    assert kinds == expected


def test_windows_toast_notifier_invokes_windows_powershell_with_encoded_command(monkeypatch):
    """Real, load-bearing detail this session verified live before shipping:
    it must be `powershell.exe` (Windows PowerShell), not `pwsh`
    (PowerShell 7/Core) - only the former projects the WinRT toast type on
    this project's real dev machine. -EncodedCommand (base64), not a
    string-interpolated -Command, is what avoids any shell-quoting
    injection surface for real alert text."""
    import subprocess as subprocess_module

    calls = []

    class _FakeResult:
        returncode = 0

    def fake_run(args, capture_output, timeout):
        calls.append(args)
        return _FakeResult()

    monkeypatch.setattr("fpl_agent.alerts.engine.subprocess.run", fake_run)
    WindowsToastNotifier().send(_ALERT)

    assert len(calls) == 1
    args = calls[0]
    assert args[0] == "powershell.exe"
    assert "pwsh" not in args[0]
    assert "-EncodedCommand" in args


def test_windows_toast_notifier_delivery_failure_never_crashes(monkeypatch, db_conn):
    def fake_run(args, capture_output, timeout):
        raise FileNotFoundError("powershell.exe not found")

    monkeypatch.setattr("fpl_agent.alerts.engine.subprocess.run", fake_run)
    # Must not raise - same "one down channel must not crash the whole
    # delivery batch" contract every other Notifier here honors.
    WindowsToastNotifier(conn=db_conn).send(_ALERT)

    from fpl_agent.monitoring.source_status import get_source_health
    statuses = {s.source_name: s for s in get_source_health(db_conn)}
    assert statuses["windows_toast_alerts"].failure_count == 1


def test_windows_toast_notifier_reports_non_zero_exit_as_failure(monkeypatch, db_conn):
    class _FakeResult:
        returncode = 1

    monkeypatch.setattr("fpl_agent.alerts.engine.subprocess.run", lambda *a, **k: _FakeResult())
    WindowsToastNotifier(conn=db_conn).send(_ALERT)

    from fpl_agent.monitoring.source_status import get_source_health
    statuses = {s.source_name: s for s in get_source_health(db_conn)}
    assert statuses["windows_toast_alerts"].failure_count == 1


def test_build_toast_script_xml_escapes_untrusted_alert_text():
    """old_value/new_value are real scraped/API text (a status string, a
    price) that can contain XML-meaningful characters - must never be
    embedded raw into the toast's XML payload."""
    script = _build_toast_script("Title & <injected>", 'body "quote"')
    assert "&amp;" in script
    assert "&lt;injected&gt;" in script
    assert "<injected>" not in script
