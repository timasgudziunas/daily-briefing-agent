"""HTML email build + Gmail send (Phase 1).

Builds the digest HTML — top TL;DR, the three pillar sections (Politics,
Technology, Economy), per-item format (headline + link + 2-3 key points +
"why it matters" + prediction), and the "Open in Claude" button (preloaded with
the day's digest, defaulting to the most recent email). Sends via `yagmail` /
smtplib + Gmail app password. Subjects: `AM Briefing | M/D/YY`,
`PM Debrief | M/D/YY`.

TODO (Phase 1): implement `build_html(...)` and `send_email(...)`.
"""
