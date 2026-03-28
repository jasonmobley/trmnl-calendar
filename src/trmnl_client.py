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
    today_events: list[dict],
    tomorrow_events: list[dict],
    max_size_bytes: int = 2000,
    max_events_per_day: int = 8,
) -> dict:
    """
    Assemble the TRMNL webhook payload and enforce the size budget.

    Algorithm:
    1. Cap each event list at max_events_per_day upfront.
    2. Build the full payload dict.
    3. If the serialized JSON exceeds max_size_bytes, trim one event at a time
       from whichever day currently has more events (alternating when equal),
       until the payload fits or both lists are empty.

    Returns the full {"merge_variables": {...}} wrapper dict.
    """
    # Defensive copies so we don't mutate the caller's lists
    today_events = list(today_events[:max_events_per_day])
    tomorrow_events = list(tomorrow_events[:max_events_per_day])

    def _build(t_events: list[dict], tm_events: list[dict]) -> dict:
        return {
            "merge_variables": {
                "today_label": today_label,
                "today_count": len(t_events),
                "today_events": t_events,
                "tomorrow_label": tomorrow_label,
                "tomorrow_count": len(tm_events),
                "tomorrow_events": tm_events,
            }
        }

    payload = _build(today_events, tomorrow_events)
    payload_bytes = len(json.dumps(payload).encode("utf-8"))

    if payload_bytes > max_size_bytes:
        logger.warning(
            "Payload is %d bytes (limit %d); trimming events", payload_bytes, max_size_bytes
        )

    while payload_bytes > max_size_bytes and (today_events or tomorrow_events):
        # Trim from the longer list; if equal, trim today first
        if len(today_events) >= len(tomorrow_events) and today_events:
            today_events.pop()
        elif tomorrow_events:
            tomorrow_events.pop()
        else:
            today_events.pop()

        payload = _build(today_events, tomorrow_events)
        payload_bytes = len(json.dumps(payload).encode("utf-8"))

    logger.info(
        "Payload: %d bytes, %d today events, %d tomorrow events",
        payload_bytes,
        len(today_events),
        len(tomorrow_events),
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
