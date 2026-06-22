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
    "call_bg": "#eef2ff",    # indigo tint — forward-looking "the call"
    "call_ink": "#3730a3",
    "right": "#15803d",      # grade verdict colors
    "wrong": "#b91c1c",
    "partial": "#b45309",
}

# Verdict -> (label, color) for the PM grades section.
_VERDICT = {
    "right": ("RIGHT", _C["right"]),
    "wrong": ("WRONG", _C["wrong"]),
    "partial": ("PARTIAL", _C["partial"]),
    "open": ("OPEN", _C["muted"]),
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
        for c in item.predictions:
            conf = f" (confidence {c.confidence}%)" if c.confidence is not None else ""
            lines.append(f"  Call [{c.horizon}]: {c.call}{conf}")
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
        for c in item.predictions:
            conf = f" (confidence {c.confidence}%)" if c.confidence is not None else ""
            lines.append(f"Call [{c.horizon}]: {c.call}{conf}")
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


def _conf_color(confidence: int | None) -> str:
    if confidence is None:
        return _C["muted"]
    if confidence >= 70:
        return _C["right"]
    if confidence >= 40:
        return _C["partial"]
    return _C["muted"]


def _conf_badge(confidence: int | None) -> str:
    """A calibrated-confidence chip, color-graded by level (empty if unknown)."""
    if confidence is None:
        return ""
    return (
        f'<span style="display:inline-block;background:{_conf_color(confidence)};'
        f"color:#ffffff;font-family:{FONT};font-size:11px;font-weight:700;"
        f'padding:2px 8px;border-radius:20px;white-space:nowrap;">{confidence}%</span>'
    )


def _predictions_html(predictions) -> str:
    """Forward-looking 'the call' block: short claim, horizon, confidence chip."""
    if not predictions:
        return ""
    rows = "".join(
        f"""
        <tr>
          <td valign="top" style="padding:0 10px 6px 0;font-family:{FONT};font-size:13.5px;
             line-height:20px;color:{_C['ink_soft']};">
             <span style="color:{_C['call_ink']};font-weight:700;">{_esc(c.horizon)}</span>
             &nbsp;{_esc(c.call)}</td>
          <td valign="top" align="right" style="padding:0 0 6px 0;white-space:nowrap;">{_conf_badge(c.confidence)}</td>
        </tr>"""
        for c in predictions
    )
    return f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="margin:12px 0 0;background:{_C['call_bg']};border-radius:6px;">
          <tr><td style="padding:10px 14px;border-left:3px solid {_C['call_ink']};">
             <span style="font-family:{FONT};font-weight:700;color:{_C['call_ink']};
                text-transform:uppercase;letter-spacing:.5px;font-size:11px;">The call</span>
             <span style="font-family:{FONT};font-size:10px;color:{_C['muted']};
                margin-left:6px;">timeframe &middot; confidence</span>
             <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                style="margin:6px 0 0;">{rows}</table>
          </td></tr>
        </table>"""


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
        {_predictions_html(item.predictions)}
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


def _long_date(date: _dt.date) -> str:
    # %-d is non-portable (fails on Windows); build the day without zero-padding.
    return f"{date:%A, %B} {date.day}, {date.year}"


def _page(title: str, long_date: str, body_inner: str, footer: str) -> str:
    """The shared email shell (header band + 600px card) for AM and PM."""
    return f"""<!DOCTYPE html>
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
             letter-spacing:.5px;">{title}</div>
          <div style="font-family:{FONT};font-size:13px;color:{_C['header_sub']};
             margin-top:4px;">{long_date}</div>
        </td></tr>

        <!-- Body -->
        <tr><td style="background:{_C['page']};padding:22px 4px 4px;">
          {body_inner}
          <div style="font-family:{FONT};font-size:12px;color:{_C['muted']};
             line-height:1.6;padding:10px 4px 0;border-top:1px solid {_C['rule']};
             margin-top:8px;">{footer}</div>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body></html>"""


def build_html(briefing: Briefing) -> tuple[str, str]:
    """Return (subject, html) for the AM Briefing."""
    subject = subject_for(briefing.date, "AM Briefing")

    sections = ""
    for pillar in PILLARS:
        sections += _section_html(pillar, [i for i in briefing.items if i.pillar == pillar])
    leftover = [i for i in briefing.items if i.pillar not in PILLARS]
    if leftover:
        sections += _section_html("More", leftover)

    body = f"{_button_html(briefing)}{_tldr_html(briefing)}{sections}"
    footer = (
        "Curated for signal over noise &middot; key points + source links only, "
        "so you read the real stories, not lossy summaries."
    )
    return subject, _page("AM&nbsp;Briefing", _long_date(briefing.date), body, footer)


# ── PM Debrief build ──────────────────────────────────────────────────────────

def _verdict_pill(status: str) -> str:
    label, color = _VERDICT.get(status, _VERDICT["open"])
    return (
        f'<span style="display:inline-block;background:{color};color:#ffffff;'
        f"font-size:11px;font-weight:700;letter-spacing:.4px;text-transform:uppercase;"
        f'padding:3px 9px;border-radius:20px;">{label}</span>'
    )


def _grade_card_html(grade) -> str:
    """One graded prediction: verdict pill + the call, outcome, and why."""
    outcome = (
        f'<div style="font-family:{FONT};font-size:13px;line-height:19px;'
        f'color:{_C["muted"]};margin-top:6px;"><b>Outcome:</b> {_esc(grade.outcome)}</div>'
        if grade.outcome else ""
    )
    why = (
        f'<div style="font-family:{FONT};font-size:13px;line-height:19px;'
        f'color:{_C["muted"]};margin-top:3px;"><b>Why:</b> {_esc(grade.why)}</div>'
        if grade.why else ""
    )
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:0 0 10px;background:{_C['card']};border:1px solid {_C['item_border']};
       border-radius:10px;">
      <tr><td style="padding:14px 18px;">
        <div style="margin:0 0 6px;">{_verdict_pill(grade.status)}
          <span style="font-family:{FONT};font-size:11px;color:{_C['muted']};
             margin-left:8px;">{_esc(grade.horizon)} &middot; called {_esc(grade.created)}</span></div>
        <div style="font-family:{FONT};font-size:14.5px;line-height:21px;
           color:{_C['ink']};font-weight:600;">{_esc(grade.call)}</div>
        {outcome}{why}
      </td></tr>
    </table>"""


def _grades_html(grades) -> str:
    inner = "".join(_grade_card_html(g) for g in grades) if grades else (
        f'<div style="font-family:{FONT};font-size:14px;color:{_C["muted"]};'
        f'padding:2px 0 8px;">No predictions came due today.</div>'
    )
    return _pillar_divider("Prediction Scorecard") + inner


def _move_color(direction: str) -> str:
    return {"up": _C["right"], "down": _C["wrong"]}.get(direction, _C["muted"])


def _wrap_bullets_html(lines: list[str]) -> str:
    """The narrative 'what moved & why' bullets above the moves grid."""
    if not lines:
        return ""
    rows = "".join(
        f"""
        <tr>
          <td valign="top" style="padding:0 8px 6px 0;font-family:{FONT};font-size:14px;
             line-height:21px;color:{_C['accent']};font-weight:700;">&#8250;</td>
          <td valign="top" style="padding:0 0 6px 0;font-family:{FONT};font-size:14px;
             line-height:21px;color:{_C['ink_soft']};">{_esc(w)}</td>
        </tr>"""
        for w in lines
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:2px 0 14px;">{rows}</table>'
    )


def _group_header_html(group: str, first: bool) -> str:
    top = "0" if first else "14px"
    return (
        f'<div style="font-family:{FONT};font-size:11px;font-weight:700;'
        f'letter-spacing:1px;text-transform:uppercase;color:{_C["muted"]};'
        f'margin:{top} 0 6px;">{_esc(group)}</div>'
    )


def _move_row_html(r) -> str:
    return f"""<tr>
          <td style="font-family:{FONT};font-size:14px;line-height:22px;color:{_C['ink']};
             font-weight:600;padding:1px 0;">{_esc(r.label)}</td>
          <td align="right" style="font-family:{FONT};font-size:13px;line-height:22px;
             color:{_C['muted']};padding:1px 12px 1px 0;white-space:nowrap;">{_esc(r.level)}</td>
          <td align="right" width="78" style="font-family:{FONT};font-size:14px;line-height:22px;
             font-weight:700;color:{_move_color(r.direction)};white-space:nowrap;">{_esc(r.change)}</td>
        </tr>"""


def _moves_grid_html(rows) -> str:
    """The Market Summary data grid: group sub-headers + label / level / % change."""
    if not rows:
        return ""
    inner = ""
    last_group = None
    for r in rows:
        if r.group != last_group:
            if last_group is not None:
                inner += "</table>"
            inner += _group_header_html(r.group, first=last_group is None)
            inner += ('<table role="presentation" width="100%" cellpadding="0" '
                      'cellspacing="0" border="0">')
            last_group = r.group
        inner += _move_row_html(r)
    inner += "</table>"
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:0 0 14px;background:{_C["card"]};border:1px solid '
        f'{_C["item_border"]};border-radius:10px;">'
        f'<tr><td style="padding:14px 18px;">{inner}</td></tr></table>'
    )


def _market_summary_html(wrap_lines: list[str], rows) -> str:
    if not wrap_lines and not rows:
        return ""
    return (
        _pillar_divider("Market Summary")
        + _wrap_bullets_html(wrap_lines)
        + _moves_grid_html(rows)
    )


def _something_new_html(piece) -> str:
    """The PM 'Something New' learning piece: topic tag, headline, a 'before you
    read' context lead-in, the fascinating key points, then a read-more link."""
    if not piece:
        return ""

    topic = ""
    if piece.topic:
        topic = (
            f'<span style="display:inline-block;background:{_C["accent"]};color:#ffffff;'
            f'font-family:{FONT};font-size:10px;font-weight:700;letter-spacing:.6px;'
            f'text-transform:uppercase;padding:3px 9px;border-radius:20px;'
            f'margin:0 0 10px;">{_esc(piece.topic)}</span><br>'
        )

    context = ""
    if piece.context:
        context = (
            f'<div style="font-family:{FONT};font-size:11px;font-weight:700;'
            f'letter-spacing:.5px;text-transform:uppercase;color:{_C["accent"]};'
            f'margin:12px 0 4px;">Before you read</div>'
            f'<div style="font-family:{FONT};font-size:14px;line-height:21px;'
            f'color:{_C["ink_soft"]};">{_esc(piece.context)}</div>'
        )

    points = _key_points_html(piece.key_points) if piece.key_points else ""

    read_more = (
        f'<a href="{_esc(piece.link)}" style="font-family:{FONT};font-size:13px;'
        f'font-weight:700;color:{_C["accent"]};text-decoration:none;display:inline-block;'
        f'margin:12px 0 0;">Read the full story &rarr;</a>'
    )

    return _pillar_divider("Something New") + f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:0 0 14px;background:{_C['accent_bg']};border:1px solid {_C['item_border']};
       border-radius:10px;">
      <tr><td style="padding:18px 20px;border-left:3px solid {_C['accent']};">
        {topic}
        <a href="{_esc(piece.link)}" style="font-family:{FONT};font-size:17px;
           font-weight:700;color:{_C['ink']};text-decoration:none;line-height:1.35;
           display:block;">{_esc(piece.title)}</a>
        <div style="font-family:{FONT};font-size:11px;color:{_C['muted']};margin:4px 0 0;">{_esc(piece.source)}</div>
        {context}
        {points}
        {read_more}
      </td></tr>
    </table>"""


def _pm_claude_prompt(debrief) -> str:
    lines = [
        f"This is my PM market debrief for {debrief.date:%B %d, %Y}. Keep it in "
        "context — if I've typed a question below, focus there; otherwise give me "
        "your sharpest read on how my predictions did and what to watch next.",
        "",
    ]
    if debrief.grades:
        lines.append("PREDICTION GRADES:")
        for g in debrief.grades:
            lines.append(f"[{g.status}] ({g.horizon}) {g.call} -> {g.outcome}")
        lines.append("")
    if debrief.market_wrap:
        lines.append("MARKET SUMMARY:")
        lines += [f"- {w}" for w in debrief.market_wrap]
        lines.append("")
    if debrief.market_moves:
        lines.append("MOVES: " + "; ".join(
            f"{r.label} {r.change}" for r in debrief.market_moves
        ))
        lines.append("")
    if debrief.learning:
        p = debrief.learning
        lines.append(f"SOMETHING NEW — {p.topic}: {p.title} ({p.source})")
        if p.context:
            lines.append(p.context)
        lines += [f"- {k}" for k in p.key_points]
        lines.append(p.link)
    return "\n".join(lines).strip()


def _pm_button_html(debrief) -> str:
    url = CLAUDE_NEW_CHAT + urllib.parse.quote(_pm_claude_prompt(debrief))
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 22px;">
      <tr><td align="center" bgcolor="{_C['claude']}" style="border-radius:8px;background:{_C['claude']};">
        <a href="{_esc(url)}" style="display:inline-block;
           font-family:{FONT};padding:12px 24px;font-size:14px;font-weight:700;
           color:#ffffff;text-decoration:none;">Discuss in Claude &nbsp;&rarr;</a>
      </td></tr>
    </table>"""


def render_debrief_text(debrief) -> str:
    """Compact plain-text PM rendering for the archive + email fallback."""
    lines = [f"PM Debrief — {debrief.date:%A, %B %d, %Y}", ""]
    if debrief.tldr:
        lines.append("TL;DR")
        lines += [f"- {t}" for t in debrief.tldr]
        lines.append("")
    lines.append("PREDICTION SCORECARD")
    if debrief.grades:
        for g in debrief.grades:
            lines.append(f"[{g.status.upper()}] ({g.horizon}) {g.call}")
            if g.outcome:
                lines.append(f"  Outcome: {g.outcome}")
            if g.why:
                lines.append(f"  Why: {g.why}")
    else:
        lines.append("No predictions came due today.")
    lines.append("")
    lines.append("MARKET SUMMARY")
    if debrief.market_wrap:
        lines += [f"- {w}" for w in debrief.market_wrap]
    for r in debrief.market_moves:
        lines.append(f"  {r.label:14} {r.level:>12}  {r.change}")
    lines.append("")
    if debrief.learning:
        p = debrief.learning
        lines.append(f"SOMETHING NEW — {p.topic}: {p.title} ({p.source})")
        if p.context:
            lines.append(p.context)
        lines += [f"  - {k}" for k in p.key_points]
        lines.append(p.link)
    return "\n".join(lines).strip()


def build_pm_html(debrief) -> tuple[str, str]:
    """Return (subject, html) for the PM Debrief.

    Shape: scorecard -> market summary (direction + the day's moves) -> one
    "Something New" learning piece. The AM's Politics/Tech/Economy article
    sections are intentionally absent — the evening read is a single fascinating
    non-markets story instead.
    """
    subject = subject_for(debrief.date, "PM Debrief")

    body = (
        _pm_button_html(debrief)
        + _tldr_html(debrief)
        + _grades_html(debrief.grades)
        + _market_summary_html(debrief.market_wrap, debrief.market_moves)
        + _something_new_html(debrief.learning)
    )
    footer = (
        "Grades anchored to real prices &amp; data &middot; the loop that makes "
        "tomorrow's calls sharper."
    )
    return subject, _page("PM&nbsp;Debrief", _long_date(debrief.date), body, footer)


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
