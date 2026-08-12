#!/usr/bin/env python3
"""Merge a standalone sensor log (e.g. Kestrel DROP) into GPX trackpoints.

Sensor loggers record on their own clock, with no idea where they were. GPX
tracks record where you were, with no idea how cold it was. This joins the two
on time, writing the result as a Garmin TrackPointExtension so that anything
reading GPX extensions - gpx.studio, Garmin, @raruto/leaflet-elevation - can
display it.

Values are linearly interpolated between the samples either side of each
trackpoint, weighted by the actual timestamps, so the sample interval can be
anything and can vary within a file. Nothing is ever extrapolated beyond the
log's coverage, and holes wider than --max-gap are left empty rather than
ramped across.

The sensor log's timestamps carry no UTC offset, so --tz is required.
"""

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

GPXTPX_NS = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"

# The Kestrel export puts three device rows above the header, then a units row
# below it. Rather than trust those positions, find the header by its content.
HEADER_MARKER = "DATE_TIME"

TIMESTAMP_FORMATS = (
    "%Y-%m-%d %I:%M:%S %p",  # Kestrel default, 12-hour
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)

OFFSET_PATTERN = re.compile(r"^[+-]\d{2}:?\d{2}$")

# A trkpt is either self-closing (no time, nothing to merge) or a normal block.
TRKPT_PATTERN = re.compile(r"<trkpt\b[^>]*/>|<trkpt\b[^>]*>.*?</trkpt>", re.DOTALL)
TIME_PATTERN = re.compile(r"<time>([^<]+)</time>")


class MergeError(Exception):
    """Anything that should stop the run with a readable message."""


def resolve_tz(spec):
    """Turn --tz into a tzinfo. Accepts an IANA name or a fixed offset."""
    if OFFSET_PATTERN.match(spec):
        sign = 1 if spec[0] == "+" else -1
        digits = spec[1:].replace(":", "")
        hours, minutes = int(digits[:2]), int(digits[2:])
        return timezone(sign * timedelta(hours=hours, minutes=minutes))
    try:
        return ZoneInfo(spec)
    except (ZoneInfoNotFoundError, ValueError):
        raise MergeError(
            f"unknown timezone {spec!r}: use an IANA name like Europe/Helsinki "
            f"or a fixed offset like +03:00"
        )


def parse_timestamp(raw):
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    raise MergeError(f"unrecognised timestamp {raw!r}")


def parse_sensor_csv(path, column, tz):
    """Read a sensor export into (device_info, unit, [(utc_time, value)]).

    Rows above the header are device metadata; the row below it declares units.
    Samples come back sorted ascending - the Kestrel exports newest-first.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = [row for row in csv.reader(handle) if row]

    header_index = next(
        (i for i, row in enumerate(rows) if row and HEADER_MARKER in row[0].upper()),
        None,
    )
    if header_index is None:
        raise MergeError(f"{path}: no header row containing {HEADER_MARKER!r}")

    device = {}
    for row in rows[:header_index]:
        if len(row) >= 2:
            device[row[0].strip()] = row[1].strip()

    header = [cell.strip() for cell in rows[header_index]]
    lowered = [cell.lower() for cell in header]
    try:
        value_index = lowered.index(column.strip().lower())
    except ValueError:
        raise MergeError(
            f"{path}: no column named {column!r}. Available: "
            + ", ".join(repr(c) for c in header if c)
        )

    units_row = rows[header_index + 1] if header_index + 1 < len(rows) else []
    unit = units_row[value_index].strip() if value_index < len(units_row) else ""
    # A units row has no parseable timestamp in column 0; a data row does.
    try:
        parse_timestamp(units_row[0])
        first_data = header_index + 1
        unit = ""
    except (MergeError, IndexError):
        first_data = header_index + 2

    type_index = lowered.index("data type") if "data type" in lowered else None

    samples = []
    for row in rows[first_data:]:
        if not row or not row[0].strip() or value_index >= len(row):
            continue
        if type_index is not None and type_index < len(row):
            kind = row[type_index].strip().lower()
            if kind and kind != "point":
                continue
        raw_value = row[value_index].strip()
        if not raw_value:
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        local = parse_timestamp(row[0]).replace(tzinfo=tz)
        samples.append((local.astimezone(timezone.utc), value))

    if not samples:
        raise MergeError(f"{path}: no usable samples in column {column!r}")

    samples.sort(key=lambda pair: pair[0])
    return device, unit, samples


def split_samples(samples):
    """Separate sorted samples into parallel lists, built once per run."""
    return [t for t, _ in samples], [v for _, v in samples]


def interpolate(times, values, when, max_gap):
    """Linear value at `when`, or None if uncovered or across too wide a gap."""
    if when < times[0] or when > times[-1]:
        return None

    index = bisect_left(times, when)
    if times[index] == when:
        return values[index]

    t0, t1 = times[index - 1], times[index]
    if t1 - t0 > max_gap:
        return None
    v0, v1 = values[index - 1], values[index]
    span = (t1 - t0).total_seconds()
    return v0 + (v1 - v0) * ((when - t0).total_seconds() / span)


def qualified(element):
    """Default the configured element name into the gpxtpx namespace."""
    return element if ":" in element else f"gpxtpx:{element}"


def set_extension_value(block, element, value):
    """Insert or replace `element` in a trkpt, preserving every sibling."""
    name = qualified(element)
    payload = f"<{name}>{value}</{name}>"

    existing = re.search(rf"<{re.escape(name)}>[^<]*</{re.escape(name)}>", block)
    if existing:
        return block[: existing.start()] + payload + block[existing.end() :]

    if "<gpxtpx:TrackPointExtension>" in block:
        return block.replace(
            "</gpxtpx:TrackPointExtension>",
            payload + "</gpxtpx:TrackPointExtension>",
            1,
        )

    wrapped = f"<gpxtpx:TrackPointExtension>{payload}</gpxtpx:TrackPointExtension>"
    if "<extensions>" in block:
        return block.replace("</extensions>", wrapped + "</extensions>", 1)

    return block.replace("</trkpt>", f"<extensions>{wrapped}</extensions></trkpt>", 1)


def ensure_namespace(text):
    """Declare xmlns:gpxtpx on the root if the source file omitted it."""
    if "xmlns:gpxtpx=" in text:
        return text
    match = re.search(r"<gpx\b[^>]*?(/?)>", text)
    if not match:
        raise MergeError("no <gpx> root element found")
    insert_at = match.end() - len(match.group(1)) - 1
    return text[:insert_at] + f' xmlns:gpxtpx="{GPXTPX_NS}"' + text[insert_at:]


def enrich_gpx_text(text, samples, element, max_gap, decimals=1):
    """Return (new_text, tally, written). Only trkpt blocks are ever touched."""
    tally = {"total": 0, "enriched": 0, "uncovered": 0, "gapped": 0, "stale": 0}
    written = []
    times, values = split_samples(samples)
    name = qualified(element)
    has_value = re.compile(rf"<{re.escape(name)}>")

    def replace(match):
        block = match.group(0)
        stamp = TIME_PATTERN.search(block)
        if not stamp:
            return block

        tally["total"] += 1
        when = datetime.fromisoformat(stamp.group(1).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(timezone.utc)

        value = interpolate(times, values, when, max_gap)
        if value is None:
            # Distinguish "outside the log" from "hole in the log" for the report.
            if when < times[0] or when > times[-1]:
                tally["uncovered"] += 1
            else:
                tally["gapped"] += 1
            if has_value.search(block):
                tally["stale"] += 1
            return block

        tally["enriched"] += 1
        written.append(value)
        return set_extension_value(block, element, f"{value:.{decimals}f}")

    updated = TRKPT_PATTERN.sub(replace, text)
    if tally["enriched"]:
        updated = ensure_namespace(updated)

    # Never hand back XML we haven't proved parses.
    try:
        ET.fromstring(updated)
    except ET.ParseError as error:
        raise MergeError(f"edit produced invalid XML ({error}); file left untouched")

    return updated, tally, written


def describe_window(samples, tz):
    first, last = samples[0][0], samples[-1][0]
    return (
        f"{first.astimezone(tz):%Y-%m-%d %H:%M} .. {last.astimezone(tz):%Y-%m-%d %H:%M}",
        f"{first:%Y-%m-%d %H:%M} .. {last:%Y-%m-%d %H:%M}",
    )


def merge(args):
    tz = resolve_tz(args.tz)
    device, unit, samples = parse_sensor_csv(args.csv, args.column, tz)
    max_gap = timedelta(minutes=args.max_gap)

    name = device.get("Device Name", "sensor")
    model = device.get("Device Model", "unknown model")
    serial = device.get("Serial Number", "?")
    local_window, utc_window = describe_window(samples, tz)

    print(f"{name} ({model}, s/n {serial})")
    print(
        f'  column "{args.column}", declared unit {unit or "(none)"}, '
        f"{len(samples)} samples"
    )
    print(f"  log window  {local_window} {args.tz}")
    print(f"              {utc_window} UTC")

    total_enriched = 0
    for path in args.gpx:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()

        updated, tally, written = enrich_gpx_text(
            text, samples, args.element, max_gap, args.decimals
        )
        total_enriched += tally["enriched"]

        print(f"\n{path}")
        if not tally["total"]:
            print("  no timestamped trackpoints")
            continue

        print(
            f'  {tally["total"]} trkpts: {tally["enriched"]} enriched, '
            f'{tally["uncovered"]} outside coverage, '
            f'{tally["gapped"]} skipped (gap > {args.max_gap} min)'
        )
        if written:
            print(
                f"  written     min {min(written):.1f}  max {max(written):.1f}  "
                f"avg {sum(written) / len(written):.1f} {unit or ''}".rstrip()
            )
        if tally["stale"]:
            print(
                f'  WARNING     {tally["stale"]} trkpts keep a value from an '
                f"earlier run; this run could not compute one for them"
            )

        if updated != text:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(updated)
            print(f"  wrote       {path}")
        else:
            print("  unchanged")

    if not total_enriched:
        raise MergeError(
            "no trackpoint fell inside the log's coverage - check --tz "
            f"(the log covers {utc_window} UTC)"
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Merge sensor log values into GPX trackpoints as "
        "Garmin TrackPointExtension elements.",
        epilog="example: mergeSensorGpx.py --gpx combined.gpx "
        "--csv SandWeather.csv --tz Europe/Helsinki",
    )
    parser.add_argument(
        "--gpx", required=True, nargs="+", metavar="FILE",
        help="GPX file(s) to enrich, modified in place",
    )
    parser.add_argument(
        "--csv", required=True, metavar="FILE", help="sensor log export",
    )
    parser.add_argument(
        "--tz", required=True, metavar="ZONE",
        help="timezone of the log's timestamps: an IANA name (Europe/Helsinki) "
             "or a fixed offset (+03:00). Required - the export states no offset",
    )
    parser.add_argument(
        "--column", default="Temperature", metavar="NAME",
        help="CSV column to merge (default: %(default)s)",
    )
    parser.add_argument(
        "--element", default="atemp", metavar="NAME",
        help="TrackPointExtension element to write, gpxtpx: assumed "
             "(default: %(default)s)",
    )
    parser.add_argument(
        "--max-gap", type=float, default=60.0, metavar="MINUTES",
        help="widest hole in the log to interpolate across (default: %(default)s)",
    )
    parser.add_argument(
        "--decimals", type=int, default=1, metavar="N",
        help="decimal places to write (default: %(default)s)",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        merge(args)
    except MergeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
