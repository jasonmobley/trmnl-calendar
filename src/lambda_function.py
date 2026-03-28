"""
AWS Lambda entry point for the TRMNL calendar plugin.

Fetches ICS calendar data from configured URLs, filters events for today
and tomorrow (in the configured timezone), and POSTs the payload to the
TRMNL private plugin webhook.

Triggered by an EventBridge schedule (every 15 minutes).
"""

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from calendar_parser import fetch_and_parse_calendars
from trmnl_client import build_payload, post_to_trmnl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def handler(event: dict, context) -> dict:
    """
    Lambda handler. Invoked by EventBridge on a 15-minute schedule.

    Environment variables:
        ICS_URLS          Comma-separated ICS calendar URLs (required)
        TRMNL_WEBHOOK_URL Full TRMNL webhook URL including plugin UUID (required)
        TIMEZONE          IANA timezone name (optional, default: America/New_York)
    """
    # --- Load and validate configuration ---
    ics_urls_raw = os.environ.get("ICS_URLS", "").strip()
    webhook_url = os.environ.get("TRMNL_WEBHOOK_URL", "").strip()
    tz_name = os.environ.get("TIMEZONE", "America/New_York").strip()

    missing = []
    if not ics_urls_raw:
        missing.append("ICS_URLS")
    if not webhook_url:
        missing.append("TRMNL_WEBHOOK_URL")
    if missing:
        logger.error("Missing required environment variable(s): %s", ", ".join(missing))
        return {"statusCode": 500, "body": f"Missing env vars: {', '.join(missing)}"}

    ics_urls = [u.strip() for u in ics_urls_raw.split(",") if u.strip()]
    if not ics_urls:
        logger.error("ICS_URLS is set but contains no valid URLs")
        return {"statusCode": 500, "body": "ICS_URLS contains no valid URLs"}

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.error("Unknown timezone: %s — falling back to America/New_York", tz_name)
        tz = ZoneInfo("America/New_York")

    # --- Determine today and tomorrow in the target timezone ---
    now = datetime.now(tz)
    today = now.date()
    tomorrow = today + timedelta(days=1)

    # Cross-platform date labels ("Friday, Mar 27" — avoids %-d on macOS)
    today_label = f"{today.strftime('%A, %b')} {today.day}"
    tomorrow_label = f"{tomorrow.strftime('%A, %b')} {tomorrow.day}"

    logger.info(
        "Fetching calendar events for %s and %s from %d URL(s)",
        today_label,
        tomorrow_label,
        len(ics_urls),
    )

    # --- Fetch and parse ICS calendars ---
    events = fetch_and_parse_calendars(ics_urls, today, tz)

    # --- Build TRMNL payload (with 2KB size guard) ---
    payload = build_payload(
        today_label=today_label,
        tomorrow_label=tomorrow_label,
        today_events=events["today"],
        tomorrow_events=events["tomorrow"],
    )

    # --- POST to TRMNL webhook ---
    success = post_to_trmnl(webhook_url, payload)

    if success:
        return {"statusCode": 200, "body": "OK"}
    else:
        return {"statusCode": 500, "body": "Failed to post to TRMNL webhook"}
