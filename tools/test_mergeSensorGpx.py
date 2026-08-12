#!/usr/bin/env python3
"""Tests for mergeSensorGpx.py. Run with: python3 -m unittest discover tools"""

import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from tempfile import NamedTemporaryFile
import os

import mergeSensorGpx as merge


UTC = timezone.utc


def at(hour, minute=0, day=4):
    return datetime(2025, 7, day, hour, minute, tzinfo=UTC)


def gpx_with(trkpts):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" '
        'version="1.1"><trk><name>Leg 1</name><trkseg>'
        + "".join(trkpts)
        + "</trkseg></trk></gpx>"
    )


def trkpt(time, extensions=""):
    return (
        f'<trkpt lat="69.1" lon="26.1"><ele>281.0</ele>'
        f"<time>{time}</time>{extensions}</trkpt>"
    )


KESTREL_CSV = "\n".join(
    [
        '"Device Name","SandWeather"',
        '"Device Model","Kestrel DROP 2"',
        '"Serial Number","2224283"',
        '"FORMATTED DATE_TIME","Temperature","Relative Humidity","Data Type"',
        '"YYYY-MM-DD HH:MM:SS","°C","%"',
        '"2025-07-04 12:00:00 PM","20.0","50.0","point"',
        '"2025-07-04 11:30:00 AM","10.0","55.0","point"',
        '"2025-07-04 11:00:00 AM","8.0","60.0","point"',
        "",
    ]
)


def write_temp(content, suffix):
    handle = NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    handle.write(content)
    handle.close()
    return handle.name


class ParseSensorCsvTest(unittest.TestCase):
    def setUp(self):
        self.path = write_temp(KESTREL_CSV, ".csv")

    def tearDown(self):
        os.unlink(self.path)

    def test_reads_device_metadata_and_declared_unit(self):
        device, unit, _ = merge.parse_sensor_csv(self.path, "Temperature", UTC)
        self.assertEqual(device["Device Name"], "SandWeather")
        self.assertEqual(device["Device Model"], "Kestrel DROP 2")
        self.assertEqual(unit, "°C")

    def test_sorts_ascending_despite_newest_first_export(self):
        _, _, samples = merge.parse_sensor_csv(self.path, "Temperature", UTC)
        self.assertEqual([v for _, v in samples], [8.0, 10.0, 20.0])

    def test_applies_timezone_to_naive_timestamps(self):
        helsinki = merge.resolve_tz("Europe/Helsinki")
        _, _, samples = merge.parse_sensor_csv(self.path, "Temperature", helsinki)
        # 11:00 local in July is 08:00 UTC
        self.assertEqual(samples[0][0], at(8))

    def test_selects_column_by_name(self):
        _, _, samples = merge.parse_sensor_csv(self.path, "Relative Humidity", UTC)
        self.assertEqual([v for _, v in samples], [60.0, 55.0, 50.0])

    def test_unknown_column_lists_what_is_available(self):
        with self.assertRaises(merge.MergeError) as caught:
            merge.parse_sensor_csv(self.path, "Wind Speed", UTC)
        self.assertIn("Temperature", str(caught.exception))

    def test_skips_non_point_rows(self):
        content = KESTREL_CSV.replace(
            '"2025-07-04 11:30:00 AM","10.0","55.0","point"',
            '"2025-07-04 11:30:00 AM","10.0","55.0","average"',
        )
        path = write_temp(content, ".csv")
        try:
            _, _, samples = merge.parse_sensor_csv(path, "Temperature", UTC)
            self.assertEqual([v for _, v in samples], [8.0, 20.0])
        finally:
            os.unlink(path)

    def test_handles_export_without_a_units_row(self):
        rows = KESTREL_CSV.splitlines()
        del rows[4]
        path = write_temp("\n".join(rows), ".csv")
        try:
            _, unit, samples = merge.parse_sensor_csv(path, "Temperature", UTC)
            self.assertEqual(unit, "")
            self.assertEqual(len(samples), 3)
        finally:
            os.unlink(path)


class ResolveTzTest(unittest.TestCase):
    def test_fixed_offsets(self):
        self.assertEqual(
            merge.resolve_tz("+03:00").utcoffset(None), timedelta(hours=3)
        )
        self.assertEqual(
            merge.resolve_tz("-0500").utcoffset(None), timedelta(hours=-5)
        )

    def test_iana_zone_follows_dst(self):
        zone = merge.resolve_tz("Europe/Helsinki")
        july = datetime(2025, 7, 10, 12, tzinfo=zone)
        october = datetime(2025, 10, 30, 12, tzinfo=zone)
        self.assertEqual(july.utcoffset(), timedelta(hours=3))
        self.assertEqual(october.utcoffset(), timedelta(hours=2))

    def test_unknown_zone_is_a_readable_error(self):
        with self.assertRaises(merge.MergeError) as caught:
            merge.resolve_tz("Mars/Olympus")
        self.assertIn("Europe/Helsinki", str(caught.exception))


class InterpolateTest(unittest.TestCase):
    def setUp(self):
        # Deliberately irregular spacing: 30 min, then 90 min.
        self.samples = [(at(8), 10.0), (at(8, 30), 20.0), (at(10), 0.0)]
        self.times, self.values = merge.split_samples(self.samples)
        self.gap = timedelta(minutes=60)

    def value_at(self, when, gap=None):
        return merge.interpolate(self.times, self.values, when, gap or self.gap)

    def test_weights_by_actual_timestamps(self):
        self.assertAlmostEqual(self.value_at(at(8, 15)), 15.0)
        self.assertAlmostEqual(self.value_at(at(8, 6)), 12.0)

    def test_exact_sample_returns_that_value(self):
        self.assertEqual(self.value_at(at(8, 30)), 20.0)

    def test_endpoints_are_covered(self):
        self.assertEqual(self.value_at(at(8)), 10.0)
        self.assertEqual(self.value_at(at(10)), 0.0)

    def test_gap_wider_than_max_gap_yields_nothing(self):
        # 08:30 -> 10:00 is 90 minutes, wider than the 60 minute guard.
        self.assertIsNone(self.value_at(at(9)))

    def test_same_gap_within_a_larger_guard_interpolates(self):
        # 09:00 is a third of the way through the 08:30 (20.0) -> 10:00 (0.0) step
        self.assertAlmostEqual(
            self.value_at(at(9), timedelta(minutes=120)), 13.333333333333334
        )

    def test_never_extrapolates_outside_coverage(self):
        self.assertIsNone(self.value_at(at(7, 59)))
        self.assertIsNone(self.value_at(at(10, 1)))


class EnrichGpxTest(unittest.TestCase):
    def setUp(self):
        self.samples = [(at(8), 10.0), (at(8, 30), 20.0)]
        self.gap = timedelta(minutes=60)

    def enrich(self, text, element="atemp"):
        return merge.enrich_gpx_text(text, self.samples, element, self.gap)

    def atemps(self, text):
        root = ET.fromstring(text)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1", "gpxtpx": merge.GPXTPX_NS}
        return [e.text for e in root.iterfind(".//gpxtpx:atemp", ns)]

    def test_creates_extensions_when_absent(self):
        text = gpx_with([trkpt("2025-07-04T08:15:00Z")])
        updated, tally, _ = self.enrich(text)
        self.assertEqual(tally["enriched"], 1)
        self.assertEqual(self.atemps(updated), ["15.0"])

    def test_writes_one_decimal(self):
        # A sixth of the way through a 10 -> 20 step is 11.666..., rounded to 11.7
        text = gpx_with([trkpt("2025-07-04T08:05:00Z")])
        updated, _, _ = self.enrich(text)
        self.assertEqual(self.atemps(updated), ["11.7"])

    def test_is_idempotent(self):
        text = gpx_with([trkpt("2025-07-04T08:15:00Z")])
        once, _, _ = self.enrich(text)
        twice, _, _ = self.enrich(once)
        self.assertEqual(once, twice)
        self.assertEqual(self.atemps(twice), ["15.0"])

    def test_replaces_a_stale_value_from_an_earlier_run(self):
        stale = (
            "<extensions><gpxtpx:TrackPointExtension>"
            "<gpxtpx:atemp>99.9</gpxtpx:atemp>"
            "</gpxtpx:TrackPointExtension></extensions>"
        )
        text = gpx_with([trkpt("2025-07-04T08:15:00Z", stale)])
        updated, _, _ = self.enrich(text)
        self.assertEqual(self.atemps(updated), ["15.0"])

    def test_preserves_sibling_extensions(self):
        with_hr = (
            "<extensions><gpxtpx:TrackPointExtension>"
            "<gpxtpx:hr>112</gpxtpx:hr>"
            "</gpxtpx:TrackPointExtension></extensions>"
        )
        text = gpx_with([trkpt("2025-07-04T08:15:00Z", with_hr)])
        updated, _, _ = self.enrich(text)
        self.assertIn("<gpxtpx:hr>112</gpxtpx:hr>", updated)
        self.assertEqual(self.atemps(updated), ["15.0"])

    def test_uncovered_and_gapped_points_are_counted_separately(self):
        samples = [(at(8), 10.0), (at(8, 30), 20.0), (at(12), 30.0)]
        text = gpx_with(
            [
                trkpt("2025-07-04T07:00:00Z"),  # before coverage
                trkpt("2025-07-04T08:15:00Z"),  # interpolated
                trkpt("2025-07-04T10:00:00Z"),  # inside a 3.5 hour hole
                trkpt("2025-07-04T13:00:00Z"),  # after coverage
            ]
        )
        _, tally, _ = merge.enrich_gpx_text(text, samples, "atemp", self.gap)
        self.assertEqual(tally["total"], 4)
        self.assertEqual(tally["enriched"], 1)
        self.assertEqual(tally["uncovered"], 2)
        self.assertEqual(tally["gapped"], 1)

    def test_flags_values_left_stale_by_a_narrower_run(self):
        stale = (
            "<extensions><gpxtpx:TrackPointExtension>"
            "<gpxtpx:atemp>99.9</gpxtpx:atemp>"
            "</gpxtpx:TrackPointExtension></extensions>"
        )
        text = gpx_with(
            [
                trkpt("2025-07-04T08:15:00Z"),
                trkpt("2025-07-04T07:00:00Z", stale),  # now outside coverage
            ]
        )
        _, tally, _ = self.enrich(text)
        self.assertEqual(tally["stale"], 1)

    def test_leaves_untimed_trackpoints_alone(self):
        text = gpx_with(
            [
                '<trkpt lat="69.1" lon="26.1"><ele>281.0</ele></trkpt>',
                trkpt("2025-07-04T08:15:00Z"),
            ]
        )
        updated, tally, _ = self.enrich(text)
        self.assertEqual(tally["total"], 1)
        self.assertEqual(self.atemps(updated), ["15.0"])

    def test_declares_the_namespace_when_the_source_omits_it(self):
        text = (
            '<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1" '
            'version="1.1"><trk><trkseg>'
            + trkpt("2025-07-04T08:15:00Z")
            + "</trkseg></trk></gpx>"
        )
        updated, _, _ = self.enrich(text)
        self.assertIn(f'xmlns:gpxtpx="{merge.GPXTPX_NS}"', updated)
        ET.fromstring(updated)

    def test_does_not_disturb_cdata_or_comments(self):
        text = gpx_with([trkpt("2025-07-04T08:15:00Z")]).replace(
            "<trk>",
            "<!-- Start photos --><wpt lat=\"69.3\" lon=\"26.1\">"
            "<desc><![CDATA[<div class=\"image-grid\"><a href=\"x.jpeg\"></a></div>]]>"
            "</desc><sym>Photo</sym></wpt><trk>",
        )
        updated, _, _ = self.enrich(text)
        self.assertIn("<!-- Start photos -->", updated)
        self.assertIn('<![CDATA[<div class="image-grid"', updated)

    def test_honours_a_custom_element_name(self):
        text = gpx_with([trkpt("2025-07-04T08:15:00Z")])
        updated, _, _ = self.enrich(text, element="hr")
        self.assertIn("<gpxtpx:hr>15.0</gpxtpx:hr>", updated)

    def test_multi_segment_tracks_keep_one_trkseg_per_trk(self):
        """togeojson <= 7.0 misindexes extensions across trksegs in one trk.

        The merge itself is structure-agnostic, but this pins the shape the
        site depends on: combineGpx.sh emits one <trk> per source file.
        """
        text = gpx_with([trkpt("2025-07-04T08:15:00Z")])
        updated, _, _ = self.enrich(text)
        root = ET.fromstring(updated)
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        for track in root.iterfind(".//gpx:trk", ns):
            self.assertEqual(len(track.findall("gpx:trkseg", ns)), 1)


if __name__ == "__main__":
    unittest.main()
