"""HTML email build + Gmail send (Phase 1).

Builds the digest HTML — top TL;DR, the three pillar sections (Politics,
Technology, Economy), per-item format (headline + link + 2-3 key points +
"why it matters"), and the "Open in Claude" button (preloaded with the day's
digest). Sends via `yagmail` (smtplib + Gmail app password). Subject:
`AM Briefing | M/D/YY`.

The HTML is table-based with inline styles only — that's what renders
consistently across Gmail (web + app), Apple Mail, and Outlook. Phase 1 has no
predictions yet (Phase 2 adds a prediction line per item).
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import logging
import smtplib
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from . import config
from .curate import PILLARS, Briefing, Item

log = logging.getLogger(__name__)

CLAUDE_NEW_CHAT = "https://claude.ai/new?q="

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

# Inline styles only — email clients strip <style> blocks and ignore classes.
_C = {
    "page": "#e9ecf1",      # page backdrop
    "card": "#ffffff",
    "header": "#0f172a",    # slate-900, editorial dark band
    "header_sub": "#94a3b8",
    "ink": "#1f2937",
    "ink_soft": "#374151",
    "muted": "#6b7280",
    "rule": "#e8eaed",
    "item_border": "#ededf2",
    "accent": "#c2410c",    # warm rust — "signal not noise"
    "accent_bg": "#fff7ed",
    "pill_bg": "#f1f5f9",
    "pill_ink": "#475569",
    "claude": "#d97757",
}


def subject_for(date: _dt.date, kind: str = "AM Briefing") -> str:
    """`AM Briefing | M/D/YY` with no zero-padding (rolling date)."""
    return f"{kind} | {date.month}/{date.day}/{date:%y}"


# ── Plain-text digest (archive) ──────────────────────────────────────────────

def render_digest_text(briefing: Briefing) -> str:
    """A compact plain-text rendering — used for the archive record."""
    lines = [f"AM Briefing — {briefing.date:%A, %B %d, %Y}", ""]
    if briefing.tldr:
        lines.append("TL;DR")
        lines += [f"- {t}" for t in briefing.tldr]
        lines.append("")
    for item in briefing.items:
        lines.append(f"[{item.pillar}] {item.headline} ({item.source})")
        lines.append(item.link)
        lines += [f"  - {p}" for p in item.key_points]
        if item.why_it_matters:
            lines.append(f"  Why it matters: {item.why_it_matters}")
        lines.append("")
    return "\n".join(lines).strip()


def _claude_prompt(briefing: Briefing) -> str:
    """Tight, single-spaced prefill for the Claude chat (no big blank gaps).

    Ends with a dual-path instruction so the user can either just press Enter for
    a general read, or type a specific question first and have Claude focus there.
    """
    lines = [
        f"This is my AM market briefing for {briefing.date:%B %d, %Y}. "
        "Keep it in context — if I've typed a question below, focus there; "
        "otherwise give me your sharpest read on what matters for my investing.",
        "",
    ]
    for item in briefing.items:
        lines.append(f"[{item.pillar}] {item.headline} ({item.source})")
        lines += [f"- {p}" for p in item.key_points]
        if item.why_it_matters:
            lines.append(f"Why it matters: {item.why_it_matters}")
        lines.append(item.link)
        lines.append("")
    return "\n".join(lines).strip()


def _claude_url(briefing: Briefing) -> str:
    return CLAUDE_NEW_CHAT + urllib.parse.quote(_claude_prompt(briefing))


# ── HTML build ───────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return _html.escape(text or "")


def _key_points_html(points: list[str]) -> str:
    """Clean hanging-indent bullets via a table (more consistent than <ul>)."""
    rows = "".join(
        f"""
        <tr>
          <td valign="top" style="padding:0 8px 7px 0;font-family:{FONT};
             font-size:14px;line-height:21px;color:{_C['accent']};font-weight:700;">&#8250;</td>
          <td valign="top" style="padding:0 0 7px 0;font-family:{FONT};
             font-size:14px;line-height:21px;color:{_C['ink_soft']};">{_esc(p)}</td>
        </tr>"""
        for p in points
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:2px 0 0;">{rows}</table>'
    )


def _item_html(item: Item) -> str:
    why = ""
    if item.why_it_matters:
        why = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="margin:12px 0 0;background:{_C['accent_bg']};border-radius:6px;">
          <tr><td style="padding:10px 14px;border-left:3px solid {_C['accent']};
             font-family:{FONT};font-size:13.5px;line-height:20px;color:{_C['ink_soft']};">
             <span style="font-weight:700;color:{_C['accent']};text-transform:uppercase;
                letter-spacing:.5px;font-size:11px;">Why it matters</span><br>
             {_esc(item.why_it_matters)}</td></tr>
        </table>"""

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:0 0 14px;background:{_C['card']};border:1px solid {_C['item_border']};
       border-radius:10px;">
      <tr><td style="padding:18px 20px;">
        <div style="font-family:{FONT};margin:0 0 8px;">
          <span style="display:inline-block;background:{_C['pill_bg']};color:{_C['pill_ink']};
             font-size:11px;font-weight:600;letter-spacing:.4px;text-transform:uppercase;
             padding:3px 9px;border-radius:20px;">{_esc(item.source)}</span>
        </div>
        <a href="{_esc(item.link)}" style="font-family:{FONT};font-size:18px;
           font-weight:700;color:{_C['ink']};text-decoration:none;line-height:1.32;
           display:block;margin:0 0 4px;">{_esc(item.headline)}</a>
        {_key_points_html(item.key_points)}
        {why}
      </td></tr>
    </table>"""


def _pillar_divider(pillar: str) -> str:
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:6px 0 14px;">
      <tr>
        <td style="font-family:{FONT};font-size:12px;font-weight:700;letter-spacing:1.5px;
           text-transform:uppercase;color:{_C['accent']};white-space:nowrap;
           padding-right:12px;">{_esc(pillar)}</td>
        <td width="100%" style="border-bottom:1px solid {_C['rule']};font-size:0;line-height:0;">&nbsp;</td>
      </tr>
    </table>"""


def _section_html(pillar: str, items: list[Item]) -> str:
    if not items:
        return ""
    return _pillar_divider(pillar) + "".join(_item_html(it) for it in items)


def _tldr_html(briefing: Briefing) -> str:
    if not briefing.tldr:
        return ""
    rows = "".join(
        f"""
        <tr>
          <td valign="top" style="padding:0 8px 6px 0;font-family:{FONT};font-size:14px;
             line-height:21px;color:{_C['accent']};font-weight:700;">&#8250;</td>
          <td valign="top" style="padding:0 0 6px 0;font-family:{FONT};font-size:14px;
             line-height:21px;color:{_C['ink_soft']};">{_esc(t)}</td>
        </tr>"""
        for t in briefing.tldr
    )
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:0 0 22px;background:{_C['card']};border:1px solid {_C['item_border']};
       border-radius:10px;">
      <tr><td style="padding:16px 20px;">
        <div style="font-family:{FONT};font-size:12px;font-weight:700;letter-spacing:1.5px;
           text-transform:uppercase;color:{_C['muted']};margin:0 0 10px;">The TL;DR</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>
      </td></tr>
    </table>"""


def _button_html(briefing: Briefing) -> str:
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 22px;">
      <tr><td align="center" bgcolor="{_C['claude']}" style="border-radius:8px;background:{_C['claude']};">
        <a href="{_esc(_claude_url(briefing))}" style="display:inline-block;
           font-family:{FONT};padding:12px 24px;font-size:14px;font-weight:700;
           color:#ffffff;text-decoration:none;">Discuss in Claude &nbsp;&rarr;</a>
      </td></tr>
    </table>"""


def build_html(briefing: Briefing) -> tuple[str, str]:
    """Return (subject, html) for the AM Briefing."""
    subject = subject_for(briefing.date, "AM Briefing")
    # %-d is non-portable (fails on Windows); build the day without zero-padding.
    long_date = f"{briefing.date:%A, %B} {briefing.date.day}, {briefing.date.year}"

    sections = ""
    for pillar in PILLARS:
        sections += _section_html(pillar, [i for i in briefing.items if i.pillar == pillar])
    leftover = [i for i in briefing.items if i.pillar not in PILLARS]
    if leftover:
        sections += _section_html("More", leftover)

    return subject, f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="color-scheme" content="light only"></head>
<body style="margin:0;padding:0;background:{_C['page']};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
     style="background:{_C['page']};">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
         style="width:600px;max-width:600px;">

        <!-- Header band -->
        <tr><td style="background:{_C['header']};border-radius:12px 12px 0 0;
           border-top:4px solid {_C['accent']};padding:26px 28px;">
          <div style="font-family:{FONT};font-size:20px;font-weight:800;color:#ffffff;
             letter-spacing:.5px;">AM&nbsp;Briefing</div>
          <div style="font-family:{FONT};font-size:13px;color:{_C['header_sub']};
             margin-top:4px;">{long_date}</div>
        </td></tr>

        <!-- Body -->
        <tr><td style="background:{_C['page']};padding:22px 4px 4px;">
          {_button_html(briefing)}
          {_tldr_html(briefing)}
          {sections}
          <div style="font-family:{FONT};font-size:12px;color:{_C['muted']};
             line-height:1.6;padding:10px 4px 0;border-top:1px solid {_C['rule']};
             margin-top:8px;">
             Curated for signal over noise &middot; key points + source links only,
             so you read the real stories, not lossy summaries.
          </div>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body></html>"""


# ── Send ─────────────────────────────────────────────────────────────────────

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_SSL_PORT = 465


def send_email(
    subject: str,
    html: str,
    text: str | None = None,
    to: str | None = None,
    from_name: str = "Daily Briefing",
) -> None:
    """Send the HTML email via Gmail over SMTP (app password).

    The message is a proper ``MIMEMultipart('alternative')``: a plain-text part
    first (fallback), then the HTML part LAST with subtype ``'html'`` — last wins,
    so any modern client renders the HTML instead of showing raw tags. Earlier we
    leaned on yagmail's HTML auto-detection, which mis-tagged the body as plain
    text; building the MIME explicitly fixes that.

    Raises a clear error if the Gmail credentials are not configured, so a
    missing app password fails loudly rather than silently dropping the send.
    """
    address = config.get_secret("GMAIL_ADDRESS")
    app_password = config.get_secret("GMAIL_APP_PASSWORD")
    if not address or not app_password:
        raise RuntimeError(
            "Gmail not configured: set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env "
            "(use a Gmail App Password, not your account password)."
        )

    recipient = to or address  # default: send to self

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, address))
    msg["To"] = recipient

    # Plain-text fallback first, HTML last (clients prefer the last part).
    fallback = text or "Open this email in an HTML-capable client to read the briefing."
    msg.attach(MIMEText(fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_SSL_PORT) as server:
        server.login(address, app_password)
        server.sendmail(address, [recipient], msg.as_string())
    log.info("Sent %r to %s", subject, recipient)
