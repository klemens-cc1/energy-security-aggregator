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


def render_html(articles: dict, date_str: str, from_addr: str = "") -> str:
    grouped = articles
    total = sum(len(v) for v in grouped.values())

    category_blocks = ""
    for category, items in grouped.items():
        icon = CATEGORY_ICONS.get(category, "📰")

        # Red accent divider bar above each category
        rows = ""
        for a in items:
            title = html.escape(a.get("title", ""), quote=False)
            url = html.escape(a.get("url", ""), quote=True)
            feed_name = html.escape(a.get("feed_name", ""), quote=False)
            rows += f"""
              <tr>
                <td style="padding: 9px 0; border-bottom: 1px solid #f0f0f0;">
                  <a href="{url}"
                     style="font-family: Merriweather, Georgia, Times, serif;
                            font-size: 14px; line-height: 1.5; color: #1a1a1a;
                            text-decoration: none; display: block;">
                    {title}
                  </a>
                  <span style="font-family: Oswald, 'Arial Narrow', Helvetica Neue, Arial, sans-serif;
                               font-size: 11px; color: #909090; letter-spacing: 0.5px;
                               text-transform: uppercase;">
                    {feed_name}
                  </span>
                </td>
              </tr>"""

        category_blocks += f"""
        <!-- Red accent bar -->
        <tr><td style="background: #ba0c2f; height: 3px; font-size: 0; line-height: 0;">&nbsp;</td></tr>
        <!-- Category header -->
        <tr>
          <td style="padding: 14px 0 2px 0;">
            <p style="margin: 0;
                      font-family: Oswald, 'Arial Narrow', Helvetica Neue, Arial, sans-serif;
                      font-size: 13px; font-weight: 400; text-transform: uppercase;
                      letter-spacing: 2px; color: #ba0c2f;">
              {icon}&nbsp; {category} &nbsp;<span style="color: #c0c0c0; font-size: 11px;">({len(items)})</span>
            </p>
          </td>
        </tr>
        <!-- Articles -->
        <tr>
          <td style="padding-bottom: 18px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              {rows}
            </table>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #efefef;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #efefef;">
    <tr>
      <td align="center" style="padding: 24px 16px;">

        <table width="610" cellpadding="0" cellspacing="0" border="0"
               style="background-color: #ffffff; color: #000; width: 610px; margin: 0 auto;">

          <!-- Header: charcoal background, UGA red accent, Oswald font -->
          <tr>
            <td style="background-color: #252525; padding: 28px 36px 24px 36px;">
              <p style="margin: 0;
                        font-family: Oswald, 'Arial Narrow', Helvetica Neue, Arial, sans-serif;
                        font-size: 11px; font-weight: 400; text-transform: uppercase;
                        letter-spacing: 3px; color: #ba0c2f;">
                Weekly Digest
              </p>
              <p style="margin: 8px 0 0 0;
                        font-family: Merriweather, Georgia, Times, serif;
                        font-size: 24px; font-weight: 400; color: #ffffff; line-height: 1.2;">
                Energy Security Briefing
              </p>
              <p style="margin: 10px 0 0 0;
                        font-family: Oswald, 'Arial Narrow', Helvetica Neue, Arial, sans-serif;
                        font-size: 13px; color: #909090; letter-spacing: 0.5px;">
                {date_str} &nbsp;&middot;&nbsp; {total} articles
              </p>
            </td>
          </tr>

          <!-- Content -->
          <tr>
            <td style="padding: 4px 36px 28px 36px; background-color: #ffffff;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                {category_blocks}
              </table>
            </td>
          </tr>

          <!-- Footer: charcoal background matching header -->
          <tr>
            <td style="background-color: #252525; padding: 20px 36px;">
              <p style="margin: 0;
                        font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, sans-serif;
                        font-size: 11px; color: #909090; text-align: center; line-height: 1.8;">
                Energy Security Aggregator &nbsp;&middot;&nbsp; Automated weekly digest
                <br>
                <a href="mailto:{from_addr}?subject=Unsubscribe&amp;body=Please%20unsubscribe%20me."
                   style="color: #ba0c2f; text-decoration: none;">Unsubscribe</a>
              </p>
            </td>
          </tr>

        </table>

      </td>
    </tr>
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
    lines.append("To unsubscribe reply to this email with subject: Unsubscribe")

    return "\n".join(lines)


def send_email(articles: dict) -> bool:
    """Send the digest email. Returns True on success."""
    if not articles:
        log.info("No new articles — skipping email.")
        return False

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    from_addr = os.environ.get("FROM_ADDRESS", smtp_user)
    recipients = [r.strip() for r in os.environ["RECIPIENT_EMAILS"].split(",")]

    date_str = datetime.now().strftime("%A, %B %-d, %Y")
    subject = f"Energy Security Weekly — {date_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Energy Security Digest <{from_addr}>"
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(render_plain(articles, date_str), "plain"))
    msg.attach(MIMEText(render_html(articles, date_str, from_addr), "html"))

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
