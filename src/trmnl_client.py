"""
TRMNL private plugin webhook client.

Builds the merge_variables payload and POSTs it to the TRMNL webhook endpoint.
Enforces the 2KB payload size limit before sending.
"""

import json
import logging

import requests

logger = logging.getLogger(__name__)


def build_payload(
    today_label: str,
    tomorrow_label: str,
    today_allday: list[dict],
    today_timed: list[dict],
    tomorrow_allday: list[dict],
    tomorrow_timed: list[dict],
    max_size_bytes: int = 2000,
    max_events_per_day: int = 8,
) -> dict:
    """
    Assemble the TRMNL webhook payload and enforce the size budget.

    All-day and timed events are kept in separate fields so the template can
    render them differently.

    If the payload exceeds max_size_bytes, tomorrow's events are dropped
    entirely so today's events are always shown in full.

    Returns the full {"merge_variables": {...}} wrapper dict.
    """
    # Defensive copies, capped upfront
    today_allday = list(today_allday[:max_events_per_day])
    today_timed = list(today_timed[:max_events_per_day])
    tomorrow_allday = list(tomorrow_allday[:max_events_per_day])
    tomorrow_timed = list(tomorrow_timed[:max_events_per_day])

    def _build(t_allday, t_timed, tm_allday, tm_timed) -> dict:
        return {
            "merge_variables": {
                "today_label": today_label,
                "today_allday_count": len(t_allday),
                "today_allday_events": t_allday,
                "today_timed_count": len(t_timed),
                "today_timed_events": t_timed,
                "tomorrow_label": tomorrow_label,
                "tomorrow_allday_count": len(tm_allday),
                "tomorrow_allday_events": tm_allday,
                "tomorrow_timed_count": len(tm_timed),
                "tomorrow_timed_events": tm_timed,
            }
        }

    payload = _build(today_allday, today_timed, tomorrow_allday, tomorrow_timed)
    payload_bytes = len(json.dumps(payload).encode("utf-8"))

    if payload_bytes > max_size_bytes:
        logger.warning(
            "Payload is %d bytes (limit %d); dropping tomorrow events", payload_bytes, max_size_bytes
        )
        tomorrow_allday = []
        tomorrow_timed = []
        payload = _build(today_allday, today_timed, tomorrow_allday, tomorrow_timed)
        payload_bytes = len(json.dumps(payload).encode("utf-8"))

    logger.info(
        "Payload: %d bytes — today %d all-day + %d timed, tomorrow %d all-day + %d timed",
        payload_bytes,
        len(today_allday), len(today_timed),
        len(tomorrow_allday), len(tomorrow_timed),
    )

    return payload


def post_to_trmnl(
    webhook_url: str,
    payload: dict,
    timeout: int = 15,
) -> bool:
    """
    POST the payload as JSON to the TRMNL webhook URL.

    Returns True on a 2xx response, False on any error.
    Never raises — logs failures and returns False.
    """
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        if response.ok:
            logger.info("TRMNL webhook POST successful: %d", response.status_code)
            return True
        else:
            logger.error(
                "TRMNL webhook POST failed: %d — %s",
                response.status_code,
                response.text[:200],
            )
            return False
    except requests.exceptions.Timeout:
        logger.error("TRMNL webhook POST timed out after %ds", timeout)
    except requests.exceptions.ConnectionError as e:
        logger.error("TRMNL webhook POST connection error: %s", e)
    except Exception as e:
        logger.error("TRMNL webhook POST unexpected error: %s", e)
    return False
