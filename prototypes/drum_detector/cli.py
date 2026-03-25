from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyzer import DEFAULT_SPLIT_DENSITY, analyze_file, iter_audio_files


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SampleRod drum detector prototype")
    parser.add_argument("target", help="audio file or folder to analyze")
    parser.add_argument("--recursive", action="store_true", help="scan folders recursively")
    parser.add_argument("--top-n", type=int, default=5, help="number of candidates to keep")
    parser.add_argument(
        "--split-density",
        type=float,
        default=DEFAULT_SPLIT_DENSITY,
        help="initial transient split density from 0 (sparse) to 100 (dense)",
    )
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    targets = list(iter_audio_files(args.target, recursive=args.recursive))
    if not targets:
        parser.error(f"no supported audio files found in {Path(args.target).expanduser()}")

    payload = []
    for source in targets:
        result = analyze_file(source, top_n=args.top_n, split_density=args.split_density)
        payload.append(result.to_dict())
        if args.json:
            continue

        print(source)
        print(
            f"  result      : {result.label} "
            f"({result.family} / {result.form}, conf {result.confidence:.2f})"
        )
        print(
            f"  groove      : break {result.break_score:.2f} | loop {result.loop_score:.2f} | "
            f"tempo {result.tempo_bpm:.1f} bpm"
        )
        print(
            f"  energy      : drum {result.drum_score:.2f} | perc {result.percussive_ratio:.2f} | "
            f"harm {result.harmonic_ratio:.2f}"
        )
        print(
            f"  hits        : {result.onset_count} transient(s)"
            f" - {', '.join(hit.label for hit in result.transient_hits[:6]) or '-'}"
        )
        for candidate in result.candidates:
            print(f"    - {candidate.label:<14} {candidate.score:.2f}  {candidate.details}")
        print()

    if args.json:
        print(json.dumps(payload[0] if len(payload) == 1 else payload, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
