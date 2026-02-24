import os
import html
import smtplib
import logging
from collections import defaultdict
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

CATEGORY_ICONS = {
    "AI & Data Centers": "🤖",
    "Renewables": "🌱",
    "Nuclear": "☢️",
    "Hydrocarbons": "🛢️",
    "Georgia & Southeast US": "🍑",
    "General": "📰",
}


def group_by_category(articles: list[dict]) -> dict:
    grouped = defaultdict(list)
    for article in articles:
        grouped[article["category"]].append(article)
    return dict(grouped)


def render_html(articles: dict, date_str: str) -> str:
    grouped = articles  # already categorized and ordered

    total = sum(len(v) for v in grouped.values())
    category_blocks = ""
    for category, items in grouped.items():
        icon = CATEGORY_ICONS.get(category, "📰")
        rows = ""
        for a in items:
            title = html.escape(a.get("title", ""), quote=False)
            url = html.escape(a.get("url", ""), quote=True)
            feed_name = html.escape(a.get("feed_name", ""), quote=False)
            rows += f"""
            <tr>
              <td style="padding: 8px 0; border-bottom: 1px solid #f0f0f0;">
                <a href="{url}" style="color: #1a1a2e; text-decoration: none; font-size: 14px; line-height: 1.5;">
                  {title}
                </a>
                <span style="color: #888; font-size: 12px; margin-left: 8px;">— {feed_name}</span>
              </td>
            </tr>"""

        category_blocks += f"""
        <tr>
          <td style="padding: 20px 0 4px 0;">
            <p style="margin: 0; font-size: 13px; font-weight: 700; text-transform: uppercase;
                       letter-spacing: 1px; color: #555; border-bottom: 2px solid #e63946;
                       padding-bottom: 6px;">
              {icon} {category}
            </p>
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              {rows}
            </table>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin: 0; padding: 0; background: #f5f5f5; font-family: Georgia, serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background: #f5f5f5;">
    <tr><td align="center" style="padding: 24px 16px;">
      <table width="620" cellpadding="0" cellspacing="0" border="0"
             style="background: #ffffff; border-radius: 4px; overflow: hidden;
                    box-shadow: 0 1px 4px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background: #1a1a2e; padding: 28px 36px;">
            <p style="margin: 0; color: #e63946; font-size: 11px; font-weight: 700;
                       text-transform: uppercase; letter-spacing: 2px;">Weekly Digest</p>
            <h1 style="margin: 6px 0 0 0; color: #ffffff; font-size: 22px; font-weight: 400;">
              Energy Security Briefing
            </h1>
            <p style="margin: 8px 0 0 0; color: #aaaacc; font-size: 13px;">{date_str} &nbsp;·&nbsp; {total} articles</p>
          </td>
        </tr>

        <!-- Content -->
        <tr>
          <td style="padding: 8px 36px 28px 36px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              {category_blocks}
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background: #f9f9f9; padding: 16px 36px; border-top: 1px solid #eee;">
            <p style="margin: 0; color: #aaa; font-size: 11px; text-align: center;">
              Energy Security Aggregator · Automated weekly digest
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def render_plain(articles: dict, date_str: str) -> str:
    total = sum(len(v) for v in articles.values())
    lines = [
        "ENERGY SECURITY WEEKLY",
        date_str,
        f"{total} articles",
        "",
        "=" * 60,
        "",
    ]

    for category, items in articles.items():
        icon = CATEGORY_ICONS.get(category, "")
        lines.append(f"{icon} {category.upper()}  ({len(items)} articles)")
        lines.append("-" * 60)
        lines.append("")

        for i, a in enumerate(items, 1):
            lines.append(f"{i}. {a['title']}")
            lines.append(f"   {a['feed_name']}")
            lines.append(f"   {a['url']}")
            lines.append("")

        lines.append("")

    lines.append("=" * 60)
    lines.append("Energy Security Aggregator · Automated weekly digest")

    return "\n".join(lines)


def send_email(articles: dict) -> bool:
    """Send the digest email. Returns True on success."""
    if not articles:
        log.info("No new articles — skipping email.")
        return False

    # Required env vars
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    from_addr = os.environ.get("FROM_ADDRESS", smtp_user)
    # Comma-separated list of recipient emails
    recipients = [r.strip() for r in os.environ["RECIPIENT_EMAILS"].split(",")]

    date_str = datetime.now().strftime("%A, %B %-d, %Y")
    subject = f"Energy Security Weekly — {date_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Energy Security Digest <{from_addr}>"
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(render_plain(articles, date_str), "plain"))
    msg.attach(MIMEText(render_html(articles, date_str), "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, recipients, msg.as_string())
        log.info(f"Email sent to {len(recipients)} recipient(s) with {sum(len(v) for v in articles.values())} articles.")
        return True
    except Exception as e:
        log.error(f"Failed to send email: {e}")
        raise
