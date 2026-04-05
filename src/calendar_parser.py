"""
ICS calendar fetching, parsing, and event normalization.

Fetches one or more ICS URLs, expands recurring events, and returns
normalized event dicts for today and tomorrow sorted by start time.
"""

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 40


def fetch_ics(url: str, timeout: int = 10) -> icalendar.Calendar | None:
    """
    GET the ICS URL and return a parsed Calendar object.

    Returns None on any error (network, HTTP, or parse failure).
    Never raises — callers can safely iterate over multiple URLs.
    """
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        cal = icalendar.Calendar.from_ical(response.content)
        logger.info("Fetched ICS from %s", url)
        return cal
    except requests.exceptions.Timeout:
        logger.warning("Timeout fetching ICS from %s", url)
    except requests.exceptions.ConnectionError as e:
        logger.warning("Connection error fetching ICS from %s: %s", url, e)
    except requests.exceptions.HTTPError as e:
        logger.warning("HTTP error fetching ICS from %s: %s", url, e)
    except Exception as e:
        logger.warning("Failed to fetch/parse ICS from %s: %s", url, e)
    return None


def normalize_event(component: icalendar.cal.Event, tz: ZoneInfo) -> dict:
    """
    Convert a VEVENT component into a compact event dict.

    Timed event:   {"time": "9:00 AM", "end_time": "9:30 AM", "title": "..."}
    All-day event: {"time": "All day", "title": "..."}

    Also includes a "_sort_key" datetime used for sorting (removed by caller).
    """
    # --- Title ---
    summary = str(component.get("SUMMARY", "(No title)")).strip() or "(No title)"
    if len(summary) > MAX_TITLE_LENGTH:
        summary = summary[:MAX_TITLE_LENGTH - 3] + "..."

    # --- Start time ---
    dtstart = component.get("DTSTART")
    if dtstart is None:
        return {"time": "All day", "title": summary, "_sort_key": datetime.min.replace(tzinfo=tz)}

    start = dtstart.dt

    # All-day: DTSTART is a date, not a datetime
    if isinstance(start, date) and not isinstance(start, datetime):
        sort_key = datetime(start.year, start.month, start.day, 0, 0, tzinfo=tz)
        return {"time": "All day", "title": summary, "_sort_key": sort_key}

    # Timed event: convert to target timezone
    if start.tzinfo is None:
        # Floating time — treat as already in target tz
        start = start.replace(tzinfo=tz)
    else:
        start = start.astimezone(tz)

    # --- End time ---
    dtend = component.get("DTEND")
    duration = component.get("DURATION")

    end = None
    if dtend is not None:
        end_raw = dtend.dt
        if isinstance(end_raw, datetime):
            if end_raw.tzinfo is None:
                end_raw = end_raw.replace(tzinfo=tz)
            else:
                end_raw = end_raw.astimezone(tz)
            end = end_raw
    elif duration is not None:
        end = start + duration.dt

    event: dict = {
        "time": start.strftime("%-I:%M %p").lstrip("0") if start.minute != 0
        else start.strftime("%-I %p"),
        "title": summary,
        "_sort_key": start,
    }

    if end is not None and isinstance(end, datetime):
        event["end_time"] = (
            end.strftime("%-I:%M %p").lstrip("0") if end.minute != 0
            else end.strftime("%-I %p")
        )

    return event


def _format_time(dt: datetime) -> str:
    """Format a datetime as a clean time string like '9:00 AM' or '9 AM'."""
    if dt.minute == 0:
        return dt.strftime("%-I %p")
    return dt.strftime("%-I:%M %p")


def get_events_for_date(
    cal: icalendar.Calendar,
    day: date,
    tz: ZoneInfo,
) -> list[dict]:
    """
    Expand and return all events (including recurring) for a single day.

    Uses recurring_ical_events to correctly expand RRULE, EXDATE, RDATE, etc.
    Returns a list of normalized event dicts (with _sort_key included).
    """
    start_dt = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end_dt = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=tz)

    try:
        components = recurring_ical_events.of(cal).between(start_dt, end_dt)
    except Exception as e:
        logger.warning("Error expanding recurring events for %s: %s", day, e)
        return []

    events = []
    for component in components:
        if component.name == "VEVENT":
            try:
                event = normalize_event(component, tz)
                events.append(event)
            except Exception as e:
                logger.warning("Error normalizing event: %s", e)

    return events


def _calendar_name(url: str) -> str:
    """
    Derive a display name from an ICS URL.

    Takes the last path segment, strips the .ics extension, and returns the
    result.  E.g. '.../work_calendar.ics' → 'work_calendar'.
    Falls back to the full URL if the segment can't be parsed.
    """
    segment = url.rstrip("/").rsplit("/", 1)[-1]
    if segment.lower().endswith(".ics"):
        segment = segment[:-4]
    return segment or url


def fetch_and_parse_calendars(
    ics_urls: list[str],
    today: date,
    tz: ZoneInfo,
) -> dict[str, list[dict]]:
    """
    Fetch all ICS URLs and return events for today and tomorrow.

    Returns:
        {
            "today_allday": [...], "today_timed": [...],
            "tomorrow_allday": [...], "tomorrow_timed": [...],
        }

    Events across calendars are deduplicated: if the same title, start time,
    and end time appear in multiple calendars the event is emitted once with a
    "calendars" field listing each calendar name the event appears on.

    Events are sorted by start time (all-day events first).
    Failed URL fetches are skipped; partial data from successful URLs is returned.
    """
    total_calendars = len(ics_urls)
    tomorrow = today + timedelta(days=1)

    today_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=tz)
    today_end = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=tz)
    tomorrow_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0, tzinfo=tz)
    tomorrow_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59, 59, tzinfo=tz)
    logger.info(
        "Matching today %s – %s, tomorrow %s – %s",
        today_start.isoformat(), today_end.isoformat(),
        tomorrow_start.isoformat(), tomorrow_end.isoformat(),
    )

    # Collect (cal_name, event) pairs without prefixing titles yet
    today_raw: list[tuple[str, dict]] = []
    tomorrow_raw: list[tuple[str, dict]] = []

    for url in ics_urls:
        cal = fetch_ics(url)
        if cal is None:
            continue

        cal_name = _calendar_name(url)
        for event in get_events_for_date(cal, today, tz):
            today_raw.append((cal_name, event))
        for event in get_events_for_date(cal, tomorrow, tz):
            tomorrow_raw.append((cal_name, event))

    def _dedup_and_prefix(raw: list[tuple[str, dict]]) -> list[dict]:
        """
        Merge events with identical (title, time, end_time) across calendars,
        collecting their calendar names into a "calendars" field.
        """
        # Use an ordered structure to preserve first-seen sort order
        seen_keys: list[tuple] = []
        cal_names_by_key: dict[tuple, list[str]] = {}
        event_by_key: dict[tuple, dict] = {}

        for cal_name, event in raw:
            key = (event["title"], event["time"], event.get("end_time"))
            if key not in event_by_key:
                seen_keys.append(key)
                cal_names_by_key[key] = []
                event_by_key[key] = event
            if cal_name not in cal_names_by_key[key]:
                cal_names_by_key[key].append(cal_name)

        result = []
        for key in seen_keys:
            event = dict(event_by_key[key])
            event["calendars"] = cal_names_by_key[key]
            result.append(event)

        return result

    today_events = _dedup_and_prefix(today_raw)
    tomorrow_events = _dedup_and_prefix(tomorrow_raw)

    # Sort by _sort_key, then strip the internal sort key before returning
    today_events.sort(key=lambda e: e["_sort_key"])
    tomorrow_events.sort(key=lambda e: e["_sort_key"])

    for event in today_events + tomorrow_events:
        event.pop("_sort_key")

    def _split(events: list[dict]) -> tuple[list[dict], list[dict]]:
        allday = [e for e in events if e["time"] == "All day"]
        timed = [e for e in events if e["time"] != "All day"]
        return allday, timed

    today_allday, today_timed = _split(today_events)
    tomorrow_allday, tomorrow_timed = _split(tomorrow_events)

    logger.info(
        "Found %d all-day + %d timed event(s) today, %d all-day + %d timed event(s) tomorrow",
        len(today_allday), len(today_timed),
        len(tomorrow_allday), len(tomorrow_timed),
    )

    return {
        "today_allday": today_allday,
        "today_timed": today_timed,
        "tomorrow_allday": tomorrow_allday,
        "tomorrow_timed": tomorrow_timed,
    }
