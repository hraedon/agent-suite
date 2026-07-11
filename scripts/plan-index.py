#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import assert_never


class PlanStatus(Enum):
    PROPOSED = "Proposed"
    IN_PROGRESS = "In Progress"
    COMPLETE = "Complete"
    IMPLEMENTED = "Implemented"
    DEFERRED = "Deferred"
    UNKNOWN = "unknown"


PLAN_FILE_RE = re.compile(r"^\d{3}-.*\.md$")
NUMBER_RE = re.compile(r"^(\d+)-")
STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(.+?)(?:\s*[-(]|\s*$)", re.MULTILINE)
FALLBACK_STATUS_RE = re.compile(r"^Status:\s*(.+?)(?:\s*[-(]|\s*$)", re.MULTILINE)
DEPENDS_RE = re.compile(r"\*\*Depends?:\*\*\s*(.+?)(?:\n|\r|\*\*)", re.IGNORECASE)
SUPERSEDES_RE = re.compile(r"\*\*Supersedes:\*\*\s*(.+?)(?:\n|\r|\*\*)")
TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
DRIFT_RE = re.compile(
    r"\b(?:[Tt]his\s+[Pp]lan|[Pp]lan|\bit)\s+(?:is|was|are)\s+(?:now\s+)?"
    r"(Complete|Implemented)\b(?:[.,;:!]|[^\S\r\n]*$)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class PlanEntry:
    number: int
    title: str
    status: str
    filepath: str
    dependencies: list[str]
    supersedes: str | None


@dataclass(frozen=True)
class ValidationIssue:
    kind: str
    message: str


def _status_label(status: PlanStatus) -> str:
    match status:
        case PlanStatus.PROPOSED:
            return "Proposed"
        case PlanStatus.IN_PROGRESS:
            return "In Progress"
        case PlanStatus.COMPLETE:
            return "Complete"
        case PlanStatus.IMPLEMENTED:
            return "Implemented"
        case PlanStatus.DEFERRED:
            return "Deferred"
        case PlanStatus.UNKNOWN:
            return "unknown"
        case _:
            assert_never(status)


def _normalize_status(raw: str) -> PlanStatus:
    text = raw.strip().lower()
    if text.startswith("proposed"):
        return PlanStatus.PROPOSED
    if text.startswith("in progress"):
        return PlanStatus.IN_PROGRESS
    if text.startswith("complete"):
        return PlanStatus.COMPLETE
    if text.startswith("implemented"):
        return PlanStatus.IMPLEMENTED
    if text.startswith("deferred"):
        return PlanStatus.DEFERRED
    return PlanStatus.UNKNOWN


def _extract_title(text: str) -> str:
    match = TITLE_RE.search(text)
    if match:
        return match.group(1).strip()
    return ""


def _extract_status(text: str) -> PlanStatus:
    match = STATUS_RE.search(text)
    if not match:
        match = FALLBACK_STATUS_RE.search(text)
    if match:
        return _normalize_status(match.group(1))
    return PlanStatus.UNKNOWN


def _split_list(text: str) -> list[str]:
    items = re.split(r"[,;]", text)
    return [item.strip() for item in items if item.strip()]


def _extract_dependencies(text: str) -> list[str]:
    match = DEPENDS_RE.search(text)
    if match:
        return _split_list(match.group(1))
    return []


def _extract_supersedes(text: str) -> str | None:
    match = SUPERSEDES_RE.search(text)
    if match:
        value = match.group(1).strip()
        return value if value else None
    return None


def parse_plan_file(path: Path) -> PlanEntry | None:
    filename = path.name
    if not PLAN_FILE_RE.match(filename):
        return None
    number_match = NUMBER_RE.match(filename)
    if not number_match:
        return None
    number = int(number_match.group(1))
    text = path.read_text(encoding="utf-8", errors="replace")
    title = _extract_title(text) or filename
    status = _extract_status(text)
    dependencies = _extract_dependencies(text)
    supersedes = _extract_supersedes(text)
    return PlanEntry(
        number=number,
        title=title,
        status=_status_label(status),
        filepath=str(path),
        dependencies=dependencies,
        supersedes=supersedes,
    )


def scan_repo(repo_path: Path) -> tuple[list[PlanEntry], list[str]]:
    entries: list[PlanEntry] = []
    warnings: list[str] = []
    plans_dir = repo_path / "plans"
    if not plans_dir.is_dir():
        return entries, warnings
    for path in sorted(plans_dir.iterdir()):
        if not path.is_file():
            continue
        if not NUMBER_RE.match(path.name):
            if path.suffix == ".md":
                warnings.append(f"{path}: skipping non-numeric plan filename")
            continue
        entry = parse_plan_file(path)
        if entry is not None:
            entries.append(entry)
    return entries, warnings


def _status_kind(status: str) -> PlanStatus:
    for candidate in PlanStatus:
        if candidate.value == status:
            return candidate
    return PlanStatus.UNKNOWN


def _has_body_completion(text: str) -> bool:
    status_match = STATUS_RE.search(text) or FALLBACK_STATUS_RE.search(text)
    if status_match:
        body = text[: status_match.start()] + text[status_match.end() :]
    else:
        body = text
    return bool(DRIFT_RE.search(body))


def validate_entries(entries: list[PlanEntry]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    by_number: dict[int, list[PlanEntry]] = {}
    for entry in entries:
        by_number.setdefault(entry.number, []).append(entry)
    for number, group in by_number.items():
        if len(group) > 1:
            paths = ", ".join(e.filepath for e in group)
            issues.append(ValidationIssue("error", f"duplicate plan number {number}: {paths}"))
    for entry in entries:
        status = _status_kind(entry.status)
        if status is PlanStatus.PROPOSED:
            text = Path(entry.filepath).read_text(encoding="utf-8", errors="replace")
            if _has_body_completion(text):
                issues.append(
                    ValidationIssue(
                        "warning",
                        f"{entry.filepath}: body claims Complete/Implemented "
                        "but Status line says 'Proposed'",
                    )
                )
    return issues


def _format_table(entries: list[PlanEntry]) -> str:
    lines: list[str] = []
    lines.append(f"{'Plan':<6}{'Status':<13}Title")
    lines.append(f"{'----':<6}{'-----------':<13}{'-----'}")
    for entry in entries:
        lines.append(f"{entry.number:03d}   {entry.status:<13}{entry.title}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and validate a plan index.")
    parser.add_argument("--repo", action="append", help="Repo path to scan (default: current)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--output", type=Path, help="Write output to file")
    parser.add_argument("--check", action="store_true", help="Exit non-zero on validation issues")
    args = parser.parse_args(argv)

    repos = [Path(p) for p in args.repo] if args.repo else [Path.cwd()]
    all_entries: list[PlanEntry] = []
    all_warnings: list[str] = []
    all_issues: list[ValidationIssue] = []
    for repo in repos:
        entries, warnings = scan_repo(repo)
        all_entries.extend(entries)
        all_warnings.extend(warnings)
        all_issues.extend(validate_entries(entries))

    errors = [i for i in all_issues if i.kind == "error"]
    drift_warnings = [i for i in all_issues if i.kind == "warning"]

    messages = list(all_warnings)
    for error in errors:
        messages.append(f"ERROR: {error.message}")
    for warning in drift_warnings:
        messages.append(f"WARNING: {warning.message}")

    output: str
    if args.json:
        payload = {
            "plans": [asdict(entry) for entry in all_entries],
            "warnings": all_warnings + [w.message for w in drift_warnings],
            "errors": [e.message for e in errors],
        }
        output = json.dumps(payload, indent=2)
    else:
        output = _format_table(all_entries)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)

    for message in messages:
        print(message, file=sys.stderr)

    if args.check and (errors or drift_warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
