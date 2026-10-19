"""Eligibility and filters for saved terms and Python blocks; no generation."""
from datetime import date
from typing import Literal, TypedDict

from ..notes.parser import digest, normalize_code
from .spaced_repetition import priority


class QuizFilters(TypedDict, total=False):
    quiz_type: Literal['multiple-choice', 'coding']
    tags: list[str]
    exclude_tags: list[str]
    date_from: str
    date_to: str
    source_file: str
    due_only: bool
    question_ids: list[str]
    term_ids: list[str]  # Older HTTP clients use this name.
    code_hash: str
    occurrence: int
    difficulty: Literal['easy', 'medium', 'hard']
    direction: Literal['random', 'forward', 'reverse', 'source']
    length: int | Literal['all', 'until']
    python_imports: str
    model: str
    provider: Literal['ollama', 'api']
    api_url: str
    api_model: str


def filter_tags(records, tags=(), match='any'):
    """The CLI also uses this filter, without requiring the Obsidian #quiz tag."""
    if match not in ('any', 'all'):
        raise ValueError('Tag match must be any or all.')
    selected = {tag.lstrip('#').casefold() for tag in tags}
    result = []
    for record in records:
        if not record.get('active', True):
            continue
        available = {tag.casefold() for tag in record.get('tags', [])}
        matches = bool(selected & available) if match == 'any' else selected <= available
        if not selected or matches:
            result.append(record)
    return result


def available_tags(records):
    return sorted({tag for row in records if row.get('active', True)
                   for tag in row.get('tags', [])}, key=str.casefold)


def eligible(backend, kind='multiple-choice'):
    if kind not in ('multiple-choice', 'coding'):
        raise ValueError('Choose Multiple Choice or Coding.')
    rows = backend.terms if kind == 'multiple-choice' else backend.codes
    return [row for row in rows if row.get('active') and
            (kind == 'coding' or 'quiz' in {tag.casefold() for tag in row.get('tags', [])})]


def filter_questions(backend, filters: QuizFilters):
    """Apply one pipeline for catalog counts, session starts and later questions."""
    kind = filters.get('quiz_type', 'multiple-choice')
    included = _selected_tags(filters.get('tags', []))
    excluded = _selected_tags(filters.get('exclude_tags', []))
    if included & excluded:
        raise ValueError('A tag cannot be both included and excluded.')
    rows = filter_tags(eligible(backend, kind), included)
    rows = [row for row in rows if not excluded.intersection(tag.casefold() for tag in row['tags'])]
    try:
        start = date.fromisoformat(filters['date_from']) if filters.get('date_from') else None
        end = date.fromisoformat(filters['date_to']) if filters.get('date_to') else None
    except (ValueError, TypeError):
        raise ValueError('Use dates in YYYY-MM-DD format.')
    if start and end and start > end:
        raise ValueError('Start date must be on or before end date.')

    if start or end:
        rows = [row for row in rows if _has_date(row['tags'], start, end)]
    if filters.get('source_file'):
        rows = [row for row in rows if row['source_file'] == filters['source_file']]
    if filters.get('due_only'):
        rows = [row for row in rows if priority(row) <= 1]
    identities = filters.get('question_ids', filters.get('term_ids'))
    if identities:
        rows = [row for row in rows if row['source_id'] in identities]
    if kind == 'coding' and filters.get('code_hash'):
        rows = [row for row in rows if digest(normalize_code(row['original_code'])) == filters['code_hash']
                and row.get('occurrence', 1) == filters.get('occurrence', 1)]
    # Difficulty selects generated blanks, not a subset of source programs.
    if filters.get('difficulty', 'medium') not in ('easy', 'medium', 'hard'):
        raise ValueError('Difficulty must be easy, medium, or hard.')
    return rows


def _selected_tags(values):
    if not isinstance(values, list) or not all(isinstance(tag, str) for tag in values):
        raise ValueError('Tags must be a list of strings.')
    return {tag.lstrip('#').casefold() for tag in values if tag.lstrip('#').casefold() != 'quiz'}


def _has_date(tags, start, end):
    for tag in tags:
        try:
            day = date.fromisoformat(tag.removeprefix('date/').replace('/', '-'))
        except ValueError:
            continue
        if (not start or day >= start) and (not end or day <= end):
            return True
    return False
