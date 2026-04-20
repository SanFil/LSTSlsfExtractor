#!/usr/bin/env python3
"""
lsf2csv — Convert DUNE LSF mission logs to CSV files.

Usage examples:

  # List all message types in a log:
  python lsf2csv.py /path/to/Data.lsf.gz --list

  # Export specific message types to CSV (one CSV per message type):
  python lsf2csv.py /path/to/Data.lsf.gz -m EstimatedState -m GpsFix

  # Export all message types (one CSV per type):
  python lsf2csv.py /path/to/Data.lsf.gz --all

  # Export to a specific output directory:
  python lsf2csv.py /path/to/Data.lsf.gz -m EstimatedState -o /tmp/output

  # Use a specific IMC.xml definitions file:
  python lsf2csv.py /path/to/Data.lsf.gz --imc /path/to/IMC.xml -m GpsFix

  # Merge all selected message types into a single CSV:
  python lsf2csv.py /path/to/Data.lsf.gz -m Temperature -m Pressure --merge

  # Show human-readable timestamps:
  python lsf2csv.py /path/to/Data.lsf.gz -m EstimatedState --human-time

  # Resolve entity IDs to human-readable names:
  python lsf2csv.py /path/to/Data.lsf.gz -m EstimatedState --resolve-entities

  # Batch-process all Data.lsf.gz files under a log directory:
  python lsf2csv.py /path/to/log/dir/ --batch -m EstimatedState -m GpsFix

  # Lat/lon in degrees instead of radians:
  python lsf2csv.py /path/to/Data.lsf.gz -m EstimatedState --degrees
"""

import argparse
import csv
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from imc_parser import parse_imc_xml
from lsf_reader import IMCMessage, iter_packets

DEFAULT_IMC_XML = Path(__file__).parent.parent / "dune-software" / "NEW" / "imc" / "IMC.xml"

LAT_LON_FIELDS = {"lat", "lon"}


def flatten_fields(fields: dict, prefix: str = "") -> dict:
    """Flatten nested message fields into dot-separated keys."""
    flat = {}
    for k, v in fields.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            flat.update(flatten_fields(v, key))
        elif isinstance(v, list):
            flat[key] = str(v)
        else:
            flat[key] = v
    return flat


def format_timestamp(ts: float, human: bool = False) -> str:
    if human:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return f"{ts:.6f}"


def build_entity_map(lsf_path: Path, msg_defs: dict) -> dict[int, str]:
    """Extract entity id -> label mapping from EntityInfo messages in the log."""
    emap = {}
    for msg in iter_packets(lsf_path, msg_defs, {"EntityInfo"}):
        eid = msg.fields.get("id")
        label = msg.fields.get("label", "")
        if eid is not None and label:
            emap[eid] = label
    return emap


def collect_messages(lsf_path: Path, msg_defs: dict,
                     filter_abbrevs: set = None) -> dict[str, list[IMCMessage]]:
    """Read all packets and group by message abbreviation."""
    by_type = defaultdict(list)
    for msg in iter_packets(lsf_path, msg_defs, filter_abbrevs):
        by_type[msg.abbrev].append(msg)
    return by_type


def write_csv(messages: list[IMCMessage], output_path: Path,
              human_time: bool = False, entity_map: dict = None,
              degrees: bool = False):
    """Write a list of same-type IMCMessages to a CSV file."""
    if not messages:
        return

    all_rows = []
    all_field_keys = []
    field_key_set = set()

    for msg in messages:
        flat = flatten_fields(msg.fields)
        if degrees:
            for k in LAT_LON_FIELDS:
                if k in flat and isinstance(flat[k], (int, float)):
                    flat[k] = math.degrees(flat[k])
        for k in flat:
            if k not in field_key_set:
                field_key_set.add(k)
                all_field_keys.append(k)
        all_rows.append((msg, flat))

    header_cols = ["timestamp", "src", "src_ent", "dst", "dst_ent"]
    if entity_map:
        header_cols = ["timestamp", "src", "src_ent", "src_ent_name",
                       "dst", "dst_ent", "dst_ent_name"]
    fieldnames = header_cols + all_field_keys

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for msg, flat in all_rows:
            row = {
                "timestamp": format_timestamp(msg.header.timestamp, human_time),
                "src": msg.header.src,
                "src_ent": msg.header.src_ent,
                "dst": msg.header.dst,
                "dst_ent": msg.header.dst_ent,
            }
            if entity_map:
                row["src_ent_name"] = entity_map.get(msg.header.src_ent, "")
                row["dst_ent_name"] = entity_map.get(msg.header.dst_ent, "")
            row.update(flat)
            writer.writerow(row)


def write_merged_csv(by_type: dict[str, list[IMCMessage]], output_path: Path,
                     human_time: bool = False, entity_map: dict = None,
                     degrees: bool = False):
    """Merge multiple message types into a single CSV, sorted by timestamp."""
    all_msgs = []
    for msgs in by_type.values():
        all_msgs.extend(msgs)
    all_msgs.sort(key=lambda m: m.header.timestamp)

    all_field_keys = []
    field_key_set = set()
    for msg in all_msgs:
        flat = flatten_fields(msg.fields)
        for k in flat:
            if k not in field_key_set:
                field_key_set.add(k)
                all_field_keys.append(k)

    header_cols = ["timestamp", "message_type", "src", "src_ent", "dst", "dst_ent"]
    if entity_map:
        header_cols = ["timestamp", "message_type", "src", "src_ent",
                       "src_ent_name", "dst", "dst_ent", "dst_ent_name"]
    fieldnames = header_cols + all_field_keys

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for msg in all_msgs:
            flat = flatten_fields(msg.fields)
            if degrees:
                for k in LAT_LON_FIELDS:
                    if k in flat and isinstance(flat[k], (int, float)):
                        flat[k] = math.degrees(flat[k])
            row = {
                "timestamp": format_timestamp(msg.header.timestamp, human_time),
                "message_type": msg.abbrev,
                "src": msg.header.src,
                "src_ent": msg.header.src_ent,
                "dst": msg.header.dst,
                "dst_ent": msg.header.dst_ent,
            }
            if entity_map:
                row["src_ent_name"] = entity_map.get(msg.header.src_ent, "")
                row["dst_ent_name"] = entity_map.get(msg.header.dst_ent, "")
            row.update(flat)
            writer.writerow(row)


def list_message_types(lsf_path: Path, msg_defs: dict):
    """Print a summary of all message types in the LSF file."""
    counts = defaultdict(int)
    for msg in iter_packets(lsf_path, msg_defs):
        counts[msg.abbrev] += 1

    print(f"\n{'Message Type':<35} {'Count':>10}")
    print("-" * 47)
    for abbrev, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {abbrev:<33} {count:>10}")
    print("-" * 47)
    print(f"  {'TOTAL':<33} {sum(counts.values()):>10}")
    print(f"\n  {len(counts)} distinct message types found.\n")


def find_imc_xml(args_imc: str = None) -> Path:
    """Locate IMC.xml, checking common paths."""
    if args_imc:
        p = Path(args_imc)
        if p.exists():
            return p
        print(f"Error: Specified IMC.xml not found: {p}", file=sys.stderr)
        sys.exit(1)

    candidates = [
        DEFAULT_IMC_XML,
        Path("/home/adallolio/dune-software/NEW/imc/IMC.xml"),
        Path("/home/adallolio/dune-software/NTNU/imc/IMC.xml"),
        Path("/home/adallolio/dune-software/imc/IMC.xml"),
    ]
    for c in candidates:
        if c.exists():
            return c

    print("Error: Could not find IMC.xml. Use --imc to specify the path.",
          file=sys.stderr)
    sys.exit(1)
  
def find_imc_xml_in_dir(session_dir: Path) -> Optional[Path]:
    """
    Look for IMC.xml or IMC.xml.gz in a session directory.
    If only the .gz is found, decompress it next to the gz file and return
    the path to the decompressed IMC.xml.
    Returns None if neither is found.
    """
    import gzip as _gzip
    from typing import Optional as _Opt

    plain = session_dir / "IMC.xml"
    compressed = session_dir / "IMC.xml.gz"

    if plain.exists():
        return plain

    if compressed.exists():
        try:
            with _gzip.open(compressed, "rb") as gz_in:
                data = gz_in.read()
            plain.write_bytes(data)
            print(f"  Auto-decompressed {compressed.name} -> {plain.name}")
            return plain
        except Exception as e:
            print(f"  WARNING: Could not decompress {compressed}: {e}")
            return None

    return None


def find_lsf_files(directory: Path) -> list[Path]:
    """Recursively find all Data.lsf and Data.lsf.gz files under a directory."""
    files = []
    for pattern in ("**/Data.lsf.gz", "**/Data.lsf", "**/*.lsf.gz", "**/*.lsf"):
        files.extend(directory.glob(pattern))
    seen = set()
    unique = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return sorted(unique)


def process_single_file(lsf_path: Path, msg_defs: dict, args) -> None:
    """Process a single LSF file with the given arguments."""
    t0 = time.monotonic()

    entity_map = None
    if args.resolve_entities:
        entity_map = build_entity_map(lsf_path, msg_defs)

    filter_abbrevs = set(args.messages) if args.messages else None

    out_dir = args.output or lsf_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading {lsf_path} ...")
    by_type = collect_messages(lsf_path, msg_defs, filter_abbrevs)
    elapsed = time.monotonic() - t0

    total_msgs = sum(len(v) for v in by_type.values())
    print(f"  Decoded {total_msgs} messages ({len(by_type)} types) in {elapsed:.1f}s.")

    if args.merge:
        stem = lsf_path.stem.replace(".lsf", "")
        out_path = out_dir / f"{stem}_merged.csv"
        write_merged_csv(by_type, out_path, args.human_time, entity_map,
                         args.degrees)
        print(f"  -> {out_path}  ({total_msgs} rows)")
    else:
        for abbrev, msgs in sorted(by_type.items()):
            stem = lsf_path.stem.replace(".lsf", "")
            out_path = out_dir / f"{stem}_{abbrev}.csv"
            write_csv(msgs, out_path, args.human_time, entity_map,
                      args.degrees)
            print(f"  -> {out_path}  ({len(msgs)} rows)")


def main():
    parser = argparse.ArgumentParser(
        description="Convert DUNE LSF mission logs to CSV files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("lsf_file", type=Path,
                        help="Path to .lsf/.lsf.gz file, or directory with --batch")
    parser.add_argument("-m", "--message", action="append", dest="messages",
                        metavar="MSG",
                        help="Message type abbreviation to export (repeatable)")
    parser.add_argument("--all", action="store_true",
                        help="Export all message types")
    parser.add_argument("--list", action="store_true",
                        help="List all message types in the log and exit")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output directory (default: same as LSF file)")
    parser.add_argument("--imc", type=str, default=None,
                        help="Path to IMC.xml definitions file")
    parser.add_argument("--merge", action="store_true",
                        help="Merge all selected messages into a single CSV")
    parser.add_argument("--human-time", action="store_true",
                        help="Use human-readable timestamps (UTC)")
    parser.add_argument("--resolve-entities", action="store_true",
                        help="Add entity name columns from EntityInfo messages")
    parser.add_argument("--degrees", action="store_true",
                        help="Convert lat/lon from radians to degrees")
    parser.add_argument("--batch", action="store_true",
                        help="Process all LSF files under a directory tree")

    args = parser.parse_args()

    if not args.lsf_file.exists():
        print(f"Error: Path not found: {args.lsf_file}", file=sys.stderr)
        sys.exit(1)

    imc_xml = find_imc_xml(args.imc)
    print(f"Using IMC definitions: {imc_xml}")

    t_global = time.monotonic()
    msg_defs = parse_imc_xml(str(imc_xml))
    print(f"Loaded {len(msg_defs)} message definitions.\n")

    if args.batch or args.lsf_file.is_dir():
        lsf_dir = args.lsf_file
        if not lsf_dir.is_dir():
            print(f"Error: --batch requires a directory, got: {lsf_dir}",
                  file=sys.stderr)
            sys.exit(1)

        lsf_files = find_lsf_files(lsf_dir)
        if not lsf_files:
            print(f"No LSF files found under {lsf_dir}", file=sys.stderr)
            sys.exit(1)

        print(f"Found {len(lsf_files)} LSF files under {lsf_dir}\n")

        for i, lsf_path in enumerate(lsf_files, 1):
            print(f"[{i}/{len(lsf_files)}] ", end="")

            if args.list:
                try:
                    list_message_types(lsf_path, msg_defs)
                except EOFError as e:
                    print(f"  WARNING: Skipping {lsf_path} — truncated/corrupt file ({e})")
                except Exception as e:
                    print(f"  WARNING: Skipping {lsf_path} — unexpected error ({e})")
            else:
                out_dir = args.output
                if out_dir:
                    rel = lsf_path.parent.relative_to(lsf_dir)
                    args.output = out_dir / rel
                else:
                    args.output = None
                try:
                    process_single_file(lsf_path, msg_defs, args)
                except EOFError as e:
                    print(f"  WARNING: Skipping {lsf_path} — truncated/corrupt file ({e})")
                except Exception as e:
                    print(f"  WARNING: Skipping {lsf_path} — unexpected error ({e})")
                args.output = out_dir
            print()

        elapsed = time.monotonic() - t_global
        print(f"Batch complete. {len(lsf_files)} files in {elapsed:.1f}s total.")
        return

    if args.list:
        list_message_types(args.lsf_file, msg_defs)
        return

    if not args.messages and not args.all:
        print("Error: Specify -m MSG, --all, or --list.", file=sys.stderr)
        sys.exit(1)

    if args.messages:
        known = {m.abbrev for m in msg_defs.values()}
        unknown = set(args.messages) - known
        if unknown:
            print(f"Warning: Unknown message types: {', '.join(sorted(unknown))}",
                  file=sys.stderr)
            args.messages = [m for m in args.messages if m not in unknown]

    process_single_file(args.lsf_file, msg_defs, args)
    print(f"\nDone. Total time: {time.monotonic() - t_global:.1f}s")


if __name__ == "__main__":
    main()
