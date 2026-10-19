"""Atomic JSON writes and source synchronization. One writer at a time for this MVP."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import shutil
from typing import TypedDict

log = logging.getLogger(__name__)


class ProgressRecord(TypedDict):
    mastery: int
    correct_count: int
    incorrect_count: int
    last_seen: str | None
    next_review: str | None
    history: list[dict]


def reset_quiz_data(data_path, kind='all'):
    """Back up existing quiz JSON bytes, then clear selected collections.

    Works even when a quiz JSON file is corrupt; settings are preserved.
    """
    choices = {'terms': ['terms.json'], 'code': ['code_quizzes.json'],
               'all': ['terms.json', 'code_quizzes.json']}
    if kind not in choices:
        raise ValueError('Reset target must be terms, code, or all.')
    root = Path(data_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='reset-backup-', dir=root))
    for filename in choices[kind]:
        source = root / filename
        if source.exists():
            shutil.copy2(source, backup / filename)
    for filename in choices[kind]:
        write_json(root / filename, [])
    return backup


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, expected_type=list):
    if not path.exists():
        return expected_type()
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, expected_type):
            raise ValueError(f"Expected {expected_type.__name__}")
        if expected_type is list:
            for row in result:
                if not isinstance(row, dict) or not isinstance(row.get("source_id"), str):
                    raise ValueError("Invalid saved record")
                for key in ("mastery", "correct_count", "incorrect_count"):
                    if key in row and (type(row[key]) is not int or row[key] < 0):
                        raise ValueError(f"Invalid {key}")
                for key in ("tags", "wrong_answers", "history", "previous_generation_hashes"):
                    if key in row and not isinstance(row[key], list):
                        raise ValueError(f"Invalid {key}")
        return result
    except (OSError, ValueError) as exc:
        # Refuse to overwrite unreadable data; the CLI can still exit cleanly.
        raise ValueError(f"Cannot read {path}: {exc}. Repair or move this file before retrying.") from exc


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_records(data_path, kind):
    """Read a collection and reject damaged source/cache fields before mutation."""
    filename = 'terms.json' if kind == 'term' else 'code_quizzes.json'
    fields = ('term', 'definition', 'term_hash', 'definition_hash') if kind == 'term' else ('language', 'original_code')
    records = read_json(Path(data_path) / filename)
    for row in records:
        if not all(isinstance(row.get(key), str) for key in ('source_file', *fields)):
            raise ValueError('Saved quiz records have missing or invalid source fields. Repair the JSON data before retrying.')
        if not all(isinstance(tag, str) for tag in row.get('tags', [])):
            raise ValueError('Saved tags must be strings.')
        if not all(isinstance(event, dict) and isinstance(event.get('correct'), bool)
                   for event in row.get('history', [])):
            raise ValueError('Saved quiz history is invalid.')
        if row.get('generation_hash') and not all(isinstance(row.get(key), str)
                for key in ('generated_code', 'blank_code', 'answer', 'expected_output', 'difficulty')):
            raise ValueError('Saved code quiz is incomplete. Repair the JSON data before retrying.')
    return records


def progress_fields() -> ProgressRecord:
    return dict(mastery=0, correct_count=0, incorrect_count=0,
                last_seen=None, next_review=None, history=[])


def sync_records(existing, parsed, *, kind="term", scanned_files=None, failed_files=()):
    """Return synchronized copies. A partial scan only deactivates its own files.

    None means a complete vault scan; unreadable files retain their old records.
    """
    records = {row["source_id"]: deepcopy(row) for row in existing}
    seen = set()
    for source in parsed:
        identity = source["source_id"]
        seen.add(identity)
        row = records.get(identity)
        if row is None:
            row = {**progress_fields(), "wrong_answers": []} if kind == "term" else {
                **progress_fields(), "previous_generation_hashes": []}
            records[identity] = row
            log.info("New %s: %s", kind, source["source_file"])
        elif kind == "term" and row.get("definition_hash") != source["definition_hash"]:
            row["wrong_answers"] = []
            row["mastery"] = max(0, row.get("mastery", 0) - 2)
            row["next_review"] = timestamp()
            row["needs_regeneration"] = True
            log.info("Changed definition: %s", source["term"])
        row.update(source)
        row["active"] = True
        row.pop("deleted_at", None)
    for identity, row in records.items():
        in_scope = scanned_files is None or row["source_file"] in scanned_files
        if identity not in seen and in_scope and row["source_file"] not in failed_files and row.get("active", True):
            row.update(active=False, deleted_at=timestamp())
            log.info("Inactive %s: %s", kind, row["source_file"])
    return list(records.values())


def sync_terms(existing, parsed, **kwargs):
    return sync_records(existing, parsed, kind="term", **kwargs)
