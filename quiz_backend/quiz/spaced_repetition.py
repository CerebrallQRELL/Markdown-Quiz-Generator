"""Small replaceable scheduler shared by term and code questions."""
from datetime import datetime, timedelta, timezone
import logging
import random

INTERVALS = (0, 1, 3, 7, 14, 30, 60)


def review_time(mastery, now):
    return now + timedelta(days=INTERVALS[min(max(mastery, 0), 6)])


def record_answer(record: dict, correct: bool, now=None, **details):
    now = now or datetime.now(timezone.utc)
    before = record.get("mastery", 0)
    attempts = details.get('attempts')
    if attempts is None:
        gain = 1  # CLI answers predate interactive retry counts.
    elif attempts == 1:
        gain = 2
    elif attempts == 2:
        gain = 1
    else:
        gain = 0
    record["mastery"] = before + gain if correct else max(0, before - 2)
    counter = "correct_count" if correct else "incorrect_count"
    record[counter] = record.get(counter, 0) + 1
    record["last_seen"] = now.isoformat()
    record["next_review"] = review_time(record["mastery"], now).isoformat()
    if details.get('attempts', 1) > 1:
        interval = review_time(record['mastery'], now) - now
        record['next_review'] = (now + interval / min(details['attempts'], 4)).isoformat()
    record.setdefault("history", []).append(dict(at=now.isoformat(), source_id=record["source_id"], correct=correct,
        completed=True, first_attempt_correct=correct and details.get('attempts', 1) == 1,
        mastery_before=before, mastery_after=record['mastery'], next_review=record['next_review'], **details))
    logging.getLogger(__name__).info("Quiz result %s: %s", record["source_id"], correct)


def reset_mastery(record):
    record["mastery"] = 0
    record["next_review"] = None


def priority(record, now=None):
    now = now or datetime.now(timezone.utc)
    if not record.get("last_seen"):
        return 0
    try:
        due = datetime.fromisoformat(record["next_review"]) if record.get("next_review") else now
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        due = now
    if due <= now:
        return 1
    history = record.get("history", [])
    if history and not history[-1].get("correct", True):
        return 2
    return 3 if record.get("mastery", 0) < 4 else 4


def select_question(records, rng=None):
    rng = rng or random
    active = [row for row in records if row.get("active", True)]
    if not active:
        raise ValueError("No active questions match this selection.")
    return rng.choices(active, weights=[(20, 12, 6, 3, 1)[priority(r)] for r in active], k=1)[0]
