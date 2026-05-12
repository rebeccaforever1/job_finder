"""Automated email notification system.

Sends digest emails every 2-3 days with new high-match job positions.
Uses Python smtplib with Gmail App Password for fully automated sending.

Setup:
    Add to your .env file:
        GMAIL_USER=you@gmail.com
        GMAIL_APP_PASSWORD=your_app_password
        NOTIFY_EMAIL=you@gmail.com

    Generate an App Password at:
        https://myaccount.google.com/apppasswords
"""

import logging
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional

from storage import get_last_email_sent, get_new_jobs_since, log_email_sent

logger = logging.getLogger(__name__)

# ── Domain tagging ─────────────────────────────────────────────────────────────
# Keywords are matched against job title + description excerpt.
# Order matters — first match wins.

DOMAIN_TAGS = {
    # Government & public sector
    "king county":          "Government / Public Sector",
    "city of seattle":      "Government / Public Sector",
    "state of washington":  "Government / Public Sector",
    "government":           "Government / Public Sector",
    "public sector":        "Government / Public Sector",
    "transit":              "Government / Public Sector",
    "municipal":            "Government / Public Sector",
    "usajobs":              "Government / Public Sector",
    "federal":              "Government / Public Sector",
    "agency":               "Government / Public Sector",

    # Nonprofit & mission-driven
    "nonprofit":            "Nonprofit / Mission-Driven",
    "non-profit":           "Nonprofit / Mission-Driven",
    "ngo":                  "Nonprofit / Mission-Driven",
    "foundation":           "Nonprofit / Mission-Driven",
    "idealist":             "Nonprofit / Mission-Driven",
    "social impact":        "Nonprofit / Mission-Driven",
    "equity":               "Nonprofit / Mission-Driven",

    # Healthcare & health systems
    "health system":        "Healthcare Analytics",
    "hospital":             "Healthcare Analytics",
    "clinical":             "Healthcare Analytics",
    "payer":                "Healthcare Analytics",
    "medicaid":             "Healthcare Analytics",
    "medicare":             "Healthcare Analytics",
    "epic":                 "Healthcare Analytics",
    "ehr":                  "Healthcare Analytics",
    "patient":              "Healthcare Analytics",
    "health plan":          "Healthcare Analytics",

    # Marketing & customer analytics
    "clv":                  "Marketing / Customer Analytics",
    "ltv":                  "Marketing / Customer Analytics",
    "customer lifetime":    "Marketing / Customer Analytics",
    "media mix":            "Marketing / Customer Analytics",
    "marketing analytics":  "Marketing / Customer Analytics",
    "campaign":             "Marketing / Customer Analytics",
    "attribution":          "Marketing / Customer Analytics",
    "retention":            "Marketing / Customer Analytics",
    "growth":               "Marketing / Customer Analytics",

    # People & HR analytics
    "people analytics":     "People Analytics",
    "workforce":            "People Analytics",
    "hr analytics":         "People Analytics",
    "human resources":      "People Analytics",
    "talent":               "People Analytics",
    "organizational":       "People Analytics",

    # Product & digital analytics
    "product analytics":    "Product Analytics",
    "product data":         "Product Analytics",
    "digital analytics":    "Product Analytics",
    "google analytics":     "Product Analytics",
    "adobe analytics":      "Product Analytics",
    "experimentation":      "Product Analytics",
    "a/b test":             "Product Analytics",

    # Data engineering & platforms
    "data engineering":     "Data Engineering",
    "data platform":        "Data Engineering",
    "data infrastructure":  "Data Engineering",
    "etl":                  "Data Engineering",
    "dbt":                  "Data Engineering",
    "databricks":           "Data Engineering",
    "snowflake":            "Data Engineering",
    "pipeline":             "Data Engineering",

    # BI & reporting
    "business intelligence": "BI & Reporting",
    "tableau":              "BI & Reporting",
    "power bi":             "BI & Reporting",
    "looker":               "BI & Reporting",
    "reporting":            "BI & Reporting",
    "dashboard":            "BI & Reporting",

    # Data science & ML
    "data science":         "Data Science / ML",
    "machine learning":     "Data Science / ML",
    "predictive":           "Data Science / ML",
    "modeling":             "Data Science / ML",
    "forecasting":          "Data Science / ML",
    "mlops":                "Data Science / ML",

    # Senior leadership (cross-domain)
    "head of data":         "Data Leadership",
    "vp of data":           "Data Leadership",
    "chief data":           "Data Leadership",
    "director of data":     "Data Leadership",
    "director of analytics": "Data Leadership",
    "vp analytics":         "Data Leadership",
}

# Color coding for match scores in the email
def _score_color(score: float) -> str:
    if score >= 0.7:
        return "#27ae60"   # green
    if score >= 0.5:
        return "#f39c12"   # amber
    return "#e74c3c"       # red


def _tag_job(job: Dict) -> str:
    """Assign a domain tag based on job title and description."""
    text = (
        job.get("title", "") + " " +
        job.get("company", "") + " " +
        job.get("description", "")[:500]
    ).lower()

    for keyword, tag in DOMAIN_TAGS.items():
        if keyword in text:
            return tag

    return "Data Analytics"  # sensible default for Rebecca's target roles


# ── HTML builders ──────────────────────────────────────────────────────────────

def _build_digest_html(jobs: List[Dict]) -> str:
    """Build HTML email body for the job digest."""
    tagged: Dict[str, List[Dict]] = {}
    for job in jobs:
        tag = _tag_job(job)
        tagged.setdefault(tag, []).append(job)

    html = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                 sans-serif; max-width: 720px; margin: 0 auto; color: #333; padding: 20px;">

    <h1 style="color: #0D1B2A; border-bottom: 3px solid #028090; padding-bottom: 10px;">
        Job Finder Digest
    </h1>
    <p style="color: #666; font-size: 14px;">
        {len(jobs)} new matching position{"s" if len(jobs) != 1 else ""} found since last digest.
        Generated {datetime.now().strftime("%B %d, %Y at %I:%M %p")}.
    </p>
    """

    for tag in sorted(tagged.keys()):
        tag_jobs = sorted(
            tagged[tag],
            key=lambda j: j.get("match_score", 0),
            reverse=True,
        )
        html += f"""
        <h2 style="color: #028090; margin-top: 28px; font-size: 17px; font-weight: 600;">
            {tag} &nbsp;<span style="color: #999; font-size: 14px; font-weight: normal;">
            ({len(tag_jobs)})</span>
        </h2>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 8px;">
        <tr style="background: #f0f4f8; text-align: left;">
            <th style="padding: 8px 10px; border-bottom: 2px solid #ccc;">Role</th>
            <th style="padding: 8px 10px; border-bottom: 2px solid #ccc;">Company</th>
            <th style="padding: 8px 10px; border-bottom: 2px solid #ccc;">Location</th>
            <th style="padding: 8px 10px; border-bottom: 2px solid #ccc; text-align: center;">Score</th>
            <th style="padding: 8px 10px; border-bottom: 2px solid #ccc;">Board</th>
            <th style="padding: 8px 10px; border-bottom: 2px solid #ccc;"></th>
        </tr>
        """

        for job in tag_jobs:
            score = job.get("match_score", 0) or 0
            color = _score_color(score)
            board = job.get("board", "").replace("_", " ").title()
            loc   = (job.get("location") or "")[:35]

            html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px 10px; font-weight: 500;">
                    {job.get("title", "N/A")}
                </td>
                <td style="padding: 8px 10px;">
                    {job.get("company", "N/A")}
                </td>
                <td style="padding: 8px 10px; font-size: 12px; color: #666;">
                    {loc}
                </td>
                <td style="padding: 8px 10px; text-align: center;
                           color: {color}; font-weight: bold;">
                    {score:.0%}
                </td>
                <td style="padding: 8px 10px; font-size: 12px; color: #888;">
                    {board}
                </td>
                <td style="padding: 8px 10px;">
                    <a href="{job.get("url", "#")}"
                       style="color: #028090; text-decoration: none; font-weight: 500;">
                        View →
                    </a>
                </td>
            </tr>
            """

        html += "</table>"

    html += """
    <hr style="margin-top: 32px; border: none; border-top: 1px solid #ddd;">
    <p style="color: #aaa; font-size: 11px; margin-top: 12px;">
        Sent by job_finder &nbsp;·&nbsp; Run
        <code style="background: #f5f5f5; padding: 1px 4px; border-radius: 3px;">
        python main.py ui</code> to open the dashboard.
    </p>
    </body>
    </html>
    """
    return html


def _build_review_html(job: Dict) -> str:
    """Build HTML email body for a single application review."""
    title   = job.get("title", "Job")
    company = job.get("company", "Company")
    url     = job.get("url", "")
    score   = job.get("match_score", 0) or 0
    color   = _score_color(score)
    board   = job.get("board", "").replace("_", " ").title()
    loc     = job.get("location", "")

    return f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                 sans-serif; max-width: 600px; margin: 0 auto; color: #333; padding: 20px;">

    <h2 style="color: #0D1B2A; border-bottom: 2px solid #028090; padding-bottom: 8px;">
        Review Application: {title}
    </h2>

    <table style="font-size: 14px; border-collapse: collapse; width: 100%; margin-bottom: 20px;">
        <tr>
            <td style="padding: 6px 12px 6px 0; color: #666; width: 120px;">Company</td>
            <td style="padding: 6px 0;"><b>{company}</b></td>
        </tr>
        <tr>
            <td style="padding: 6px 12px 6px 0; color: #666;">Location</td>
            <td style="padding: 6px 0;">{loc}</td>
        </tr>
        <tr>
            <td style="padding: 6px 12px 6px 0; color: #666;">Source</td>
            <td style="padding: 6px 0;">{board}</td>
        </tr>
        <tr>
            <td style="padding: 6px 12px 6px 0; color: #666;">Match Score</td>
            <td style="padding: 6px 0; color: {color}; font-weight: bold;">{score:.0%}</td>
        </tr>
        <tr>
            <td style="padding: 6px 12px 6px 0; color: #666;">Job URL</td>
            <td style="padding: 6px 0;">
                <a href="{url}" style="color: #028090;">{url[:80]}{"..." if len(url) > 80 else ""}</a>
            </td>
        </tr>
    </table>

    <p style="background: #f0f4f8; padding: 14px 16px; border-radius: 6px;
              font-size: 14px; line-height: 1.6;">
        The tailored CV and cover letter are attached as PDFs.
        Review them, then submit your application manually through the job URL above.
    </p>

    <hr style="margin-top: 28px; border: none; border-top: 1px solid #ddd;">
    <p style="color: #aaa; font-size: 11px;">
        Sent by job_finder automation pipeline.
    </p>
    </body>
    </html>
    """


# ── Sending logic ──────────────────────────────────────────────────────────────

def _send_via_gmail(
    msg: MIMEMultipart,
    gmail_user: str,
    gmail_app_password: str,
) -> bool:
    """Send a pre-built MIME message via Gmail SMTP SSL."""
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_app_password)
            server.send_message(msg)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. "
            "Check GMAIL_USER and GMAIL_APP_PASSWORD in your .env file. "
            "Generate an App Password at https://myaccount.google.com/apppasswords"
        )
        return False
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return False


def should_send_digest(interval_days: int = 2) -> bool:
    """Return True if enough time has passed since the last digest email."""
    last = get_last_email_sent()
    if not last:
        return True
    try:
        last_sent = datetime.fromisoformat(last["sent_at"])
        return datetime.now() - last_sent >= timedelta(days=interval_days)
    except (ValueError, KeyError):
        return True


def send_digest_email(
    jobs: List[Dict],
    recipient: str,
    gmail_user: Optional[str] = None,
    gmail_app_password: Optional[str] = None,
) -> bool:
    """Send a digest email with new job matches.

    Args:
        jobs: List of job dicts (from storage).
        recipient: Email address to send to.
        gmail_user: Gmail address to send from. Falls back to GMAIL_USER env var.
        gmail_app_password: Gmail App Password. Falls back to GMAIL_APP_PASSWORD env var.

    Returns:
        True if sent successfully, False otherwise.
    """
    if not jobs:
        logger.info("No new jobs to include in digest — skipping send.")
        return False

    gmail_user         = gmail_user or os.environ.get("GMAIL_USER", "")
    gmail_app_password = gmail_app_password or os.environ.get("GMAIL_APP_PASSWORD", "")

    if not gmail_user or not gmail_app_password:
        logger.error(
            "GMAIL_USER or GMAIL_APP_PASSWORD not set. "
            "Add them to your .env file. "
            "Generate an App Password at https://myaccount.google.com/apppasswords"
        )
        return False

    subject = (
        f"Job Finder: {len(jobs)} New Match{'es' if len(jobs) != 1 else ''} "
        f"— {datetime.now().strftime('%b %d')}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = recipient
    msg.attach(MIMEText(_build_digest_html(jobs), "html"))

    success = _send_via_gmail(msg, gmail_user, gmail_app_password)

    if success:
        log_email_sent(subject, len(jobs), recipient)
        logger.info("Digest email sent to %s with %d jobs.", recipient, len(jobs))

    return success


def send_review_email(
    job: Dict,
    cv_path: Path,
    cl_path: Optional[Path],
    recipient: str,
    gmail_user: Optional[str] = None,
    gmail_app_password: Optional[str] = None,
) -> bool:
    """Send a review email with the tailored CV and cover letter attached.

    Args:
        job: Job dict for the application being reviewed.
        cv_path: Path to the tailored CV PDF.
        cl_path: Path to the cover letter PDF (optional).
        recipient: Email address to send to.
        gmail_user: Gmail address to send from. Falls back to GMAIL_USER env var.
        gmail_app_password: Gmail App Password. Falls back to GMAIL_APP_PASSWORD env var.

    Returns:
        True if sent successfully, False otherwise.
    """
    gmail_user         = gmail_user or os.environ.get("GMAIL_USER", recipient)
    gmail_app_password = gmail_app_password or os.environ.get("GMAIL_APP_PASSWORD", "")

    if not gmail_app_password:
        logger.error(
            "GMAIL_APP_PASSWORD not set. "
            "Add it to your .env file. "
            "Generate one at https://myaccount.google.com/apppasswords"
        )
        return False

    title   = job.get("title", "Job")
    company = job.get("company", "Company")
    score   = job.get("match_score", 0) or 0

    subject = f"Review Application — {title} at {company} ({score:.0%} match)"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = recipient
    msg.attach(MIMEText(_build_review_html(job), "html"))

    # Attach PDFs
    for path in [cv_path, cl_path]:
        if path and Path(path).exists():
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), Name=Path(path).name)
            part["Content-Disposition"] = f'attachment; filename="{Path(path).name}"'
            msg.attach(part)

    success = _send_via_gmail(msg, gmail_user, gmail_app_password)

    if success:
        logger.info(
            "Review email sent for %s at %s.", title, company
        )

    return success