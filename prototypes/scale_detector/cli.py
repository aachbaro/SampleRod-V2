from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .analyzer import analyze_file, iter_audio_files


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser()
    if not target.exists():
        parser.error(f"Target not found: {target}")

    if target.is_file():
        result = analyze_file(target, top_n=args.top_n)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            _print_single_result(result, top_n=args.top_n)
        return 0

    files = list(iter_audio_files(target, recursive=args.recursive))
    if not files:
        print("No supported audio files found.", file=sys.stderr)
        return 1

    results = [analyze_file(path, top_n=args.top_n) for path in files]
    if args.json:
        print(json.dumps([result.to_dict() for result in results], indent=2))
    else:
        _print_table(results)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scale-detector",
        description="Standalone scale detector prototype for SampleRod.",
    )
    parser.add_argument("target", help="Audio file or folder to analyze.")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan folders recursively.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Return structured JSON instead of a text summary.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="How many candidates to keep in the result payload.",
    )
    return parser


def _print_single_result(result, *, top_n: int) -> None:
    source = result.source_path or "<memory>"
    print(source)
    print(f"  result      : {result.label} ({result.kind}, conf {result.confidence:.2f})")
    print(
        "  dominant    : "
        f"{result.dominant_note} ({result.dominant_note_confidence:.2f})"
    )
    print(f"  active notes: {', '.join(result.active_notes) if result.active_notes else '-'}")
    print(f"  duration    : {result.duration_s:.2f}s @ {result.sample_rate} Hz")
    print("  candidates  :")
    for index, candidate in enumerate(result.candidates[:top_n], start=1):
        notes = ", ".join(candidate.notes)
        print(
            f"    {index}. {candidate.label:<22} "
            f"score={candidate.score:.3f} notes=[{notes}]"
        )


def _print_table(results: list) -> None:
    rows = []
    for result in results:
        source_name = Path(result.source_path).name if result.source_path else "<memory>"
        rows.append(
            (
                source_name,
                result.label,
                result.kind,
                f"{result.confidence:.2f}",
                result.dominant_note,
                ", ".join(result.active_notes),
            )
        )

    headers = ("file", "result", "kind", "conf", "root", "active notes")
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = min(max(widths[index], len(value)), 44)

    def _fmt(value: str, width: int) -> str:
        if len(value) <= width:
            return value.ljust(width)
        return (value[: max(0, width - 1)] + "...")[:width]

    header_line = "  ".join(_fmt(header, widths[index]) for index, header in enumerate(headers))
    print(header_line)
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(_fmt(value, widths[index]) for index, value in enumerate(row)))


if __name__ == "__main__":
    raise SystemExit(main())
