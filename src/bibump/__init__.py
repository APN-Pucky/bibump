# SPDX-FileCopyrightText: 2026-present Alexander Puck Neuwirth <alexander@neuwirth-informatik.de>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass, field

import bibtexparser
import requests
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter

import inspirehep2bib
import zenodo2bib

IGNORED_FIELDS = {"ID", "ENTRYTYPE"}
MAX_ZENODO_SEARCH_CANDIDATES = 5

RED = "\x1b[31m"
GREEN = "\x1b[32m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
CYAN = "\x1b[36m"
RESET = "\x1b[0m"


@dataclass
class Candidate:
    entry: dict
    diff: dict = field(default_factory=dict)


@dataclass
class EntryReport:
    key: str
    source: str
    old: dict
    candidates: list[Candidate]


def _make_bib_parser() -> BibTexParser:
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    return parser


def parse_bib_file(path: str) -> bibtexparser.bibdatabase.BibDatabase:
    with open(path, encoding="utf-8") as f:
        return bibtexparser.load(f, parser=_make_bib_parser())


def parse_bib_text(text: str) -> bibtexparser.bibdatabase.BibDatabase:
    return bibtexparser.loads(text, parser=_make_bib_parser())


def parse_bib_string(text: str) -> list[dict]:
    return parse_bib_text(text).entries


def is_zenodo_entry(entry: dict) -> bool:
    for key in ("doi", "url", "publisher"):
        value = entry.get(key, "")
        if "zenodo" in value.lower():
            return True
    return False


def is_inspire_entry(entry: dict) -> bool:
    if "eprint" in entry or "archiveprefix" in {k.lower() for k in entry}:
        return True
    # INSPIRE-HEP texkeys look like "Lastname:2019abc"
    key = entry.get("ID", "")
    parts = key.split(":")
    return len(parts) == 2 and parts[1][:4].isdigit()


def detect_source(entry: dict) -> str | None:
    if is_zenodo_entry(entry):
        return "zenodo"
    if is_inspire_entry(entry):
        return "inspire"
    return None


def zenodo_record_id(entry: dict) -> str | None:
    for key in ("doi", "url", "ID"):
        value = entry.get(key)
        if value:
            record_id = zenodo2bib.extract_record_id(value)
            if record_id is not None:
                return record_id
    return None


def fetch_zenodo_candidates(entry: dict) -> list[dict]:
    record_id = zenodo_record_id(entry)
    try:
        if record_id is not None:
            latest_id = zenodo2bib.latest_zenodo_record_id(record_id)
            return parse_bib_string(zenodo2bib.get_bibtex_for_record(latest_id))

        title = entry.get("title")
        if not title:
            return []
        record_ids = zenodo2bib.search_zenodo(title, size=MAX_ZENODO_SEARCH_CANDIDATES)
        candidates = []
        for rid in record_ids:
            candidates.extend(parse_bib_string(zenodo2bib.get_bibtex_for_record(rid)))
        return candidates
    except requests.RequestException:
        return []


def inspire_query(entry: dict) -> str:
    eprint = entry.get("eprint")
    if eprint:
        return f"arXiv:{eprint}"
    return entry["ID"]


def fetch_inspire_candidates(entry: dict) -> list[dict]:
    try:
        bibtex = inspirehep2bib.get_inspire_bibtex(inspire_query(entry))
    except requests.RequestException:
        return []
    if not bibtex or not bibtex.strip():
        return []
    return parse_bib_string(bibtex)


def diff_fields(old: dict, new: dict, ignore_fields: frozenset[str] = frozenset()) -> dict:
    diff = {}
    keys = (set(old) | set(new)) - IGNORED_FIELDS - ignore_fields
    for k in keys:
        old_val = old.get(k)
        new_val = new.get(k)
        if old_val != new_val:
            diff[k] = (old_val, new_val)
    return diff


def check_entry(entry: dict, ignore_fields: frozenset[str] = frozenset()) -> EntryReport | None:
    source = detect_source(entry)
    if source is None:
        return None

    if source == "zenodo":
        fetched = fetch_zenodo_candidates(entry)
    else:
        fetched = fetch_inspire_candidates(entry)

    candidates = [Candidate(entry=c, diff=diff_fields(entry, c, ignore_fields)) for c in fetched]
    candidates = [c for c in candidates if c.diff]
    return EntryReport(key=entry["ID"], source=source, old=entry, candidates=candidates)


def colorize(text: str, color: str, use_color: bool) -> str:
    return f"{color}{text}{RESET}" if use_color else text


def format_diff(diff: dict, use_color: bool) -> list[str]:
    lines = []
    for field_name in sorted(diff):
        old_val, new_val = diff[field_name]
        if old_val is not None:
            lines.append(colorize(f"    - {field_name} = {old_val}", RED, use_color))
        if new_val is not None:
            lines.append(colorize(f"    + {field_name} = {new_val}", GREEN, use_color))
    return lines


def candidate_label(candidate: Candidate) -> str:
    new_id = candidate.entry.get("ID")
    changed = ", ".join(sorted(candidate.diff))
    return f"{new_id} ({changed})"


def prompt_choice(num_candidates: int, use_color: bool) -> int:
    prompt = colorize(f"Pick [0-{num_candidates}] (default 0, keep original): ", CYAN, use_color)
    while True:
        try:
            raw = input(prompt).strip()
        except EOFError:
            return 0
        if raw == "":
            return 0
        if raw.isdigit() and 0 <= int(raw) <= num_candidates:
            return int(raw)
        print(f"Please enter a number between 0 and {num_candidates}.")


def apply_candidate(entry: dict, candidate: Candidate) -> None:
    for field_name, (_old_val, new_val) in candidate.diff.items():
        if field_name in IGNORED_FIELDS:
            continue
        if new_val is None:
            entry.pop(field_name, None)
        else:
            entry[field_name] = new_val


def format_bib_database(database) -> str:
    writer = BibTexWriter()
    writer.order_entries_by = None  # keep the original entry order
    writer.indent = "    "
    return writer.write(database)


def write_bib_file(path: str, database) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_bib_database(database))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bibump",
        description="Check a .bib file for updates available from INSPIRE-HEP and Zenodo.",
    )
    parser.add_argument(
        "bibfile",
        nargs="?",
        default=None,
        help="path to the .bib file to check (reads from stdin, writes to stdout, if omitted)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-y", "--yes", action="store_true", help="non-interactively apply the first suggested update for every entry"
    )
    mode.add_argument(
        "-n", "--dry-run", action="store_true", help="only report diffs, don't prompt or write anything"
    )
    parser.add_argument(
        "--no-backup", action="store_true", help="don't keep a .bak backup copy when writing changes"
    )
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    parser.add_argument(
        "-i",
        "--ignore",
        action="append",
        default=[],
        metavar="FIELD",
        help="field to ignore when comparing entries (repeatable, or comma-separated, "
        "e.g. --ignore keywords,note)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="also report entries with no update or no known provider"
    )
    args = parser.parse_args(argv)

    ignore_fields = frozenset(
        f.strip().lower() for v in args.ignore for f in v.split(",") if f.strip()
    )

    stdin_mode = args.bibfile is None
    # In stdin mode, stdout is reserved for the resulting .bib content (so bibump
    # can be used as a filter: `bibump < in.bib > out.bib`), so reports go to stderr.
    report_stream = sys.stderr if stdin_mode else sys.stdout

    def log(*a, **kw):
        print(*a, file=report_stream, **kw)

    use_color = report_stream.isatty() and not args.no_color and "NO_COLOR" not in os.environ

    interactive = not args.yes and not args.dry_run
    if interactive and not sys.stdin.isatty():
        log("bibump: stdin is not a tty, falling back to --dry-run")
        interactive = False
        args.dry_run = True

    if stdin_mode:
        database = parse_bib_text(sys.stdin.read())
    else:
        database = parse_bib_file(args.bibfile)

    changed = 0
    up_to_date = 0
    unknown = 0
    for entry in database.entries:
        report = check_entry(entry, ignore_fields)
        if report is None:
            unknown += 1
            if args.verbose:
                log(f"[skip] {entry.get('ID', '?')}: no known provider or no data returned")
            continue
        if not report.candidates:
            up_to_date += 1
            if args.verbose:
                log(f"[ok] {report.key}: up to date")
            continue

        log(colorize(f"[{report.source}] {report.key}", BOLD, use_color))
        for i, candidate in enumerate(report.candidates, 1):
            log(colorize(f"  option {i}: -> {candidate_label(candidate)}", DIM, use_color))
            for line in format_diff(candidate.diff, use_color):
                log(line)

        if args.dry_run:
            continue

        if args.yes:
            choice = 1
        else:
            log("  [0] keep original")
            for i, candidate in enumerate(report.candidates, 1):
                log(f"  [{i}] use option {i}")
            choice = prompt_choice(len(report.candidates), use_color)

        if choice != 0:
            apply_candidate(entry, report.candidates[choice - 1])
            changed += 1
        log()

    log(f"{changed} entr(y/ies) updated, {up_to_date} up to date, {unknown} skipped (no provider detected).")

    if stdin_mode:
        sys.stdout.write(format_bib_database(database))
    elif changed and not args.dry_run:
        if not args.no_backup:
            shutil.copyfile(args.bibfile, args.bibfile + ".bak")
        write_bib_file(args.bibfile, database)
        log(f"Wrote {changed} update(s) to {args.bibfile}")

    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
