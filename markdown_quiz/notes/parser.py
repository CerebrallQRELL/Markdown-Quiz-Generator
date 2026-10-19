"""Read-only Markdown parser with scoped tag groups and portable identities."""
import hashlib
import logging
from pathlib import Path
import re
import unicodedata
from typing import TypedDict

log = logging.getLogger(__name__)
TAG = re.compile(r"(?<![\w/])#([\w][\w/-]*)", re.UNICODE)


class ParsedSource(TypedDict):
    source_id: str
    source_file: str
    source_line: int
    tags: list[str]


class ParsedTerm(ParsedSource):
    term: str
    definition: str
    term_hash: str
    definition_hash: str


class ParsedCode(ParsedSource):
    language: str
    original_code: str
    code_hash: str
    occurrence: int


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", text)
    text = text.replace("[[", "").replace("]]", "")
    text = re.sub(r"(`+|\*{1,3}|~~)", "", text)
    text = re.sub(r"(?<!\w)_{1,2}(.+?)_{1,2}(?!\w)", r"\1", text)
    return " ".join(text.split()).casefold()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_code(code: str) -> str:
    # Preserve leading indentation: stripping it can change Python semantics.
    return "\n".join(line.rstrip() for line in code.splitlines()).strip("\n")


def code_identity(source_file, code, occurrence=1):
    base = f"{source_file}:python:{normalize_code(code)}"
    return digest(base if occurrence == 1 else f"{base}:occurrence:{occurrence}")


def extract_frontmatter(text: str) -> tuple[list[str], list[str]]:
    """Read frontmatter tags and blank metadata without shifting source lines."""
    lines = text.splitlines()
    file_tags = []
    if lines and lines[0].strip() == '---':
        reading_tags = False
        for index, metadata in enumerate(lines[1:], 1):
            if metadata.strip() == '---':
                lines[:index + 1] = [''] * (index + 1)
                break
            match = re.match(r'^tags?\s*:\s*(.*)$', metadata, re.I)
            if match:
                reading_tags = True
                file_tags.extend(t.lstrip('#') for t in re.findall(r'[\w][\w/-]*', match[1]))
            elif reading_tags and re.match(r'^\s*-\s+', metadata):
                file_tags.extend(re.findall(r'[\w][\w/-]*', metadata.lstrip().removeprefix('-')))
            elif metadata.strip():
                reading_tags = False
    return lines, file_tags


def parse_markdown(text: str, source_file: str) -> tuple[list[ParsedTerm], list[ParsedCode]]:
    """Read fences and scoped tags, extract terms, then normalize and identify them."""
    terms: dict[str, ParsedTerm] = {}
    blocks: dict[str, ParsedCode] = {}
    lines, file_tags = extract_frontmatter(text)
    tags, collecting_tags, pending = file_tags.copy(), False, None
    pending_tags = []
    fence, language, code = None, "", []
    occurrences = {}
    fence_line = 0
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if fence:
            if re.fullmatch(re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                original = normalize_code("\n".join(code))
                if language in ("python", "py") and original:
                    occurrences[original] = occurrences.get(original, 0) + 1
                    occurrence = occurrences[original]
                    identity = code_identity(source_file, original, occurrence)
                    blocks[identity] = dict(source_id=identity, source_file=source_file,
                        language="python", original_code=original, tags=tags.copy(),
                        code_hash=digest(original), occurrence=occurrence, source_line=fence_line)
                fence, code = None, []
            else:
                code.append(raw)
            continue
        opening = re.match(r"^(`{3,}|~{3,})\s*([^\s`]*)[^`]*$", line)
        if opening:
            fence, language = opening[1], opening[2].lower()
            fence_line = line_number
            pending, collecting_tags = None, False
            continue
        found_tags = TAG.findall(line)
        if found_tags and not TAG.sub("", line).strip():
            if not collecting_tags:
                tags = file_tags.copy()
            tags = list(dict.fromkeys(tags + found_tags))
            collecting_tags, pending = True, None
            continue
        if not line:
            # Blank lines may separate bold labels or a consecutive tag group.
            continue
        collecting_tags = False
        inline_tags = TAG.findall(line)
        line = TAG.sub("", line).strip()
        term, definition = None, None
        if "::" in line:
            term, definition = line.split("::", 1)
            pending = None
        elif match := re.match(r"^\*\*Term:\*\*\s*(.+)$", line, re.I):
            pending = match[1]
            pending_tags = inline_tags
        elif match := re.match(r"^\*\*Definition:\*\*\s*(.+)$", line, re.I):
            term, definition, pending = pending, match[1], None
            inline_tags = pending_tags + inline_tags
        else:
            pending = None
        if not term or not definition:
            continue
        normalized_term = normalize_text(term)
        normalized_definition = normalize_text(definition)
        if not normalized_term or not normalized_definition:
            continue
        # Saved progress depends on this exact source + normalized-term identity.
        identity = digest(f"{source_file}:{normalized_term}")
        terms[identity] = dict(source_id=identity, source_file=source_file,
            term=term.strip(), definition=definition.strip(), tags=list(dict.fromkeys(tags + inline_tags)),
            source_line=line_number,
            term_hash=digest(normalized_term), definition_hash=digest(normalized_definition))
    return list(terms.values()), list(blocks.values())


def scan_vault(vault, files=None):
    """Return terms, code blocks, scope, and unreadable files; never write notes."""
    root = Path(vault).resolve()
    if not root.is_dir():
        raise ValueError(f"Markdown directory does not exist: {root}")
    paths = list(root.rglob("*.md")) if files is None else [root / p for p in files]
    terms, blocks, failed, scope = [], [], set(), set()
    for path in paths:
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Markdown file is outside the configured vault: {path}")
        relative = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in Path(relative).parts):
            continue
        scope.add(relative)
        if path.suffix.lower() != ".md":
            continue
        try:
            parsed_terms, parsed_blocks = parse_markdown(path.read_text(encoding="utf-8-sig"), relative)
            terms.extend(parsed_terms)
            blocks.extend(parsed_blocks)
        except FileNotFoundError:
            # A scoped deletion should deactivate records, not preserve an unreadable file.
            continue
        except (OSError, UnicodeError) as exc:
            failed.add(relative)
            log.warning("Skipped unreadable Markdown %s: %s", relative, exc)
    log.info("Scanned %s files: %s terms, %s Python blocks", len(paths), len(terms), len(blocks))
    return terms, blocks, None if files is None else scope, failed
