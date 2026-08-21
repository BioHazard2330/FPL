"""
Alert engine (section 84-86). Only HIGH/CRITICAL severity change_events become
alerts - matches "don't notify me about every piece of football news." Delivery
is tracked via change_events.alerted_at so a re-run doesn't re-alert the same event.

TerminalNotifier was the only channel enabled through Phase 7 - a deliberate,
stated user choice, not a missing feature (section 84). Telegram/Discord (added
2026-08-20, Pillar 3) are opt-in: both cost nothing (Telegram's Bot API and
Discord webhooks are free with no usage cost), and both were already anticipated
in .env.example's placeholders from Phase 1 - this closes that out. Config
absence must never crash delivery: `configured_notifiers()` silently omits a
channel that isn't configured, and each network notifier catches its own
request failure rather than aborting the whole alert batch (one down channel
must not silently drop alerts on channels that ARE working).

WindowsToastNotifier (2026-08-21, live-gameweek layer) - the user explicitly
asked for push notifications but explicitly ruled out Telegram/Discord
("dont want discord or telegram notis, find a better way, not an obnoxious
one"). A native Windows 10/11 toast notification is the real answer: no
external account/bot/webhook to set up, no third-party service in the loop,
appears as a normal transient OS notification that lands in Action Center
if missed (not a modal, not a sound-forced interrupt) - genuinely the least
obnoxious real channel available on this project's own Windows-only
platform (section 20). Verified live before building this: the WinRT toast
type (`Windows.UI.Notifications.ToastNotificationManager`) loads and a real
toast displays via Windows PowerShell (`powershell.exe`) - NOT PowerShell
7/Core (`pwsh`), which this session confirmed does not project that WinRT
type the same way. Delivered via `subprocess` + `-EncodedCommand` (UTF-16LE
base64), the standard robust way to hand PowerShell dynamic string content
without any shell-quoting/injection surface - alert text is also
XML-escaped before being embedded in the toast's own XML payload, since
`old_value`/`new_value` can contain characters like `&`/`<` in a real
predicted-lineup status string. Always included when `sys.platform ==
"win32"`, no config needed (unlike Telegram/Discord's opt-in env vars) -
this project has no non-Windows deployment target (section 20's own
Windows-only scheduler scope), so there is no cross-platform gap being
papered over here."""

import subprocess
import sqlite3
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

import requests

from fpl_agent.config import get_discord_webhook_url, get_telegram_config
from fpl_agent.ingestion.sync import update_source_health

_ALERT_SEVERITIES = ("CRITICAL", "HIGH")
_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Alert:
    change_event_id: int
    event_type: str
    entity: str
    entity_id: int
    severity: str
    old_value: str | None
    new_value: str | None
    detected_at: str


class Notifier(ABC):
    @abstractmethod
    def send(self, alert: Alert) -> None: ...


class TerminalNotifier(Notifier):
    """Only channel enabled - user chose terminal-only notifications (section 84)."""

    def send(self, alert: Alert) -> None:
        print(
            f"[{alert.severity}] {alert.event_type} {alert.entity}#{alert.entity_id}: "
            f"{alert.old_value} -> {alert.new_value}  ({alert.detected_at})"
        )


_TOAST_TIMEOUT_SECONDS = 10
_TOAST_APP_ID = "PowerShell"  # a real, always-present AppUserModelID on any
# Windows 10/11 box (Windows PowerShell ships with the OS) - toasts posted
# under it show up in Action Center under "Windows PowerShell", the same
# real, honest identity a `powershell.exe`-invoked toast actually has;
# claiming a different app's identity here would be misleading, not useful.


def _build_toast_script(title: str, body: str) -> str:
    """WinRT toast XML, built via Windows PowerShell (`powershell.exe`, not
    `pwsh`/PowerShell 7 - live-verified 2026-08-21 that only the former
    projects `Windows.UI.Notifications.ToastNotificationManager` as a usable
    type accelerator on this project's real dev machine). `title`/`body` are
    XML-escaped before embedding - alert text (old_value/new_value) is real
    scraped/API text that can genuinely contain `&`/`<`/`>` (a predicted-
    lineup status string, a price value), and this toast XML has no other
    sanitization layer."""
    safe_title = _xml_escape(title)
    safe_body = _xml_escape(body)
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType=WindowsRuntime] > $null\n"
        "[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, "
        "ContentType=WindowsRuntime] > $null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType=WindowsRuntime] > $null\n"
        "$template = @'\n"
        f'<toast><visual><binding template="ToastGeneric">'
        f"<text>{safe_title}</text><text>{safe_body}</text>"
        "</binding></visual></toast>\n"
        "'@\n"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        "$xml.LoadXml($template)\n"
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml\n"
        f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{_TOAST_APP_ID}")'
        ".Show($toast)\n"
    )


class WindowsToastNotifier(Notifier):
    """Native Windows 10/11 toast notification - see this module's own
    docstring for why this replaces Telegram/Discord as the default push
    channel for this project. Delivered via `-EncodedCommand` (base64
    UTF-16LE), not string interpolation into a shell command line - avoids
    any PowerShell-quoting injection surface entirely for real, untrusted
    alert text. Non-fatal on any failure (subprocess error, non-zero exit,
    missing `powershell.exe`) - same "one down channel must never drop
    alerts on channels that ARE working" contract every other Notifier here
    already honors, and `fpl live-watch`'s own fast in-match loop calls
    `notifier.send()` in a tight poll loop where a single hung/failing
    channel must never block real-time delivery of the next event."""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self._conn = conn

    def send(self, alert: Alert) -> None:
        import base64

        title = f"[{alert.severity}] {alert.event_type}"
        body = f"{alert.entity}#{alert.entity_id}: {alert.old_value} -> {alert.new_value}"
        script = _build_toast_script(title, body)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True, timeout=_TOAST_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            message = f"windows toast delivery failed: {type(exc).__name__}"
            print(f"[{message}]")
            if self._conn is not None:
                update_source_health(self._conn, "windows_toast_alerts", success=False, error=message)
            return
        if result.returncode != 0:
            message = f"windows toast delivery failed: powershell exit {result.returncode}"
            print(f"[{message}]")
            if self._conn is not None:
                update_source_health(self._conn, "windows_toast_alerts", success=False, error=message)
            return
        if self._conn is not None:
            update_source_health(self._conn, "windows_toast_alerts", success=True, error=None)


def _alert_text(alert: Alert) -> str:
    return (
        f"[{alert.severity}] {alert.event_type} {alert.entity}#{alert.entity_id}: "
        f"{alert.old_value} -> {alert.new_value} ({alert.detected_at})"
    )


def _safe_error_message(exc: requests.RequestException, prefix: str) -> str:
    """Never interpolate str(exc) or exc's request/response objects: requests'
    own HTTPError/ConnectionError/Timeout __str__() includes the full request
    URL, which for Telegram carries the bot token in the path and for Discord
    IS the webhook secret itself. This message is persisted into
    source_health.last_error (readable via `fpl doctor`/a DB backup) and
    printed to stderr, so it must be built only from known-safe fields - same
    fix already applied to ingestion/odds_live_source.py after a real leak was
    found there."""
    response = getattr(exc, "response", None)
    if response is not None:
        return f"{prefix}: HTTP {response.status_code}"
    return f"{prefix}: request failed (see network logs)"


class TelegramNotifier(Notifier):
    """Free (Telegram's Bot API has no cost). Requires TELEGRAM_BOT_TOKEN +
    TELEGRAM_CHAT_ID (see .env.example) - config.get_telegram_config()
    returns None if either is missing, so this class is only ever
    constructed when both are genuinely set."""

    def __init__(self, bot_token: str, chat_id: str, conn: sqlite3.Connection | None = None):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._conn = conn

    def send(self, alert: Alert) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            resp = requests.post(
                url, json={"chat_id": self._chat_id, "text": _alert_text(alert)}, timeout=_TIMEOUT_SECONDS
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            # A failed push must never crash the whole delivery batch - other
            # configured channels (terminal, Discord) still need to fire.
            message = _safe_error_message(exc, "telegram alert delivery failed")
            print(f"[{message}]")
            if self._conn is not None:
                update_source_health(self._conn, "telegram_alerts", success=False, error=message)
            return
        if self._conn is not None:
            update_source_health(self._conn, "telegram_alerts", success=True, error=None)


class DiscordNotifier(Notifier):
    """Free (Discord webhooks have no cost). Requires DISCORD_WEBHOOK_URL
    (see .env.example)."""

    def __init__(self, webhook_url: str, conn: sqlite3.Connection | None = None):
        self._webhook_url = webhook_url
        self._conn = conn

    def send(self, alert: Alert) -> None:
        try:
            resp = requests.post(self._webhook_url, json={"content": _alert_text(alert)}, timeout=_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except requests.RequestException as exc:
            message = _safe_error_message(exc, "discord alert delivery failed")
            print(f"[{message}]")
            if self._conn is not None:
                update_source_health(self._conn, "discord_alerts", success=False, error=message)
            return
        if self._conn is not None:
            update_source_health(self._conn, "discord_alerts", success=True, error=None)


class CompositeNotifier(Notifier):
    """Fans out to every configured channel - one down channel must not
    silently drop alerts on channels that ARE working (each wrapped
    notifier already catches its own delivery failure, see above)."""

    def __init__(self, notifiers: list[Notifier]):
        self._notifiers = notifiers

    def send(self, alert: Alert) -> None:
        for notifier in self._notifiers:
            notifier.send(alert)


def configured_notifiers(conn: sqlite3.Connection) -> CompositeNotifier:
    """TerminalNotifier always fires (the original, still-default channel -
    section 84). WindowsToastNotifier (2026-08-21) fires whenever running on
    Windows - no config needed, unlike Telegram/Discord's opt-in env vars -
    since this project's real deployment target IS Windows (section 20's own
    scheduler scope) and this is now the standing default push channel (see
    this module's own docstring for why Telegram/Discord were explicitly
    declined for this). Telegram/Discord stay available, added only when
    their config is genuinely present; absence is silent, never an error -
    the system must keep working without them, same as ODDS_API_KEY."""
    notifiers: list[Notifier] = [TerminalNotifier()]
    if sys.platform == "win32":
        notifiers.append(WindowsToastNotifier(conn=conn))
    telegram = get_telegram_config()
    if telegram is not None:
        notifiers.append(TelegramNotifier(*telegram, conn=conn))
    discord_url = get_discord_webhook_url()
    if discord_url is not None:
        notifiers.append(DiscordNotifier(discord_url, conn=conn))
    return CompositeNotifier(notifiers)


def pending_alerts(conn: sqlite3.Connection) -> list[Alert]:
    placeholders = ",".join("?" * len(_ALERT_SEVERITIES))
    rows = conn.execute(
        f"SELECT id, event_type, entity, entity_id, severity, old_value, new_value, detected_at "
        f"FROM change_events WHERE alerted_at IS NULL AND severity IN ({placeholders}) "
        f"ORDER BY detected_at",
        _ALERT_SEVERITIES,
    ).fetchall()
    return [
        Alert(
            change_event_id=r["id"], event_type=r["event_type"], entity=r["entity"],
            entity_id=r["entity_id"], severity=r["severity"],
            old_value=r["old_value"], new_value=r["new_value"], detected_at=r["detected_at"],
        )
        for r in rows
    ]


def mark_alerted(conn: sqlite3.Connection, change_event_ids: list[int]) -> None:
    if not change_event_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "UPDATE change_events SET alerted_at=? WHERE id=?",
        [(now, cid) for cid in change_event_ids],
    )
    conn.commit()


def deliver_pending_alerts(conn: sqlite3.Connection, notifier: Notifier) -> list[Alert]:
    alerts = pending_alerts(conn)
    for alert in alerts:
        notifier.send(alert)
    mark_alerted(conn, [a.change_event_id for a in alerts])
    return alerts
