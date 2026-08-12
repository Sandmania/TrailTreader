# What
TrailTreader was born out of my need to make planning my hikes a bit easier. I also wanted to share those plans with the folks at home, so they could show them to SAR if they didn’t hear from me for a while.
From there, it evolved into a tool with which I can share the actual hiking route taken, with photos displayed in the correct geolocation on said route.

This "tool" comprises of.
- AWS Infra
- Scripts for processing gpx files and photos

**TODO** JavaScript, HTML, configuration etc. currently resides in a repository which displays a hike I completed in [Paistunturi, 2024](https://github.com/Sandmania/hikingtrips/tree/main/paistunturi2024). Some of those common files could live in this repo. Maybe an example hike, too.

## AWS Infra

`infra/NLS_revers_proxy.yaml` can be used to deploy an AWS Apigateway API that works as a reverse proxy to National Land Survey of Finland's WMTS endpoint. It is meant to hide your NLS API key.

### TODO
Current CORS settings are a bit too lax. Should be tighter.

## Match photo timestamp to a gpx trkpt time (createPhotoTrack.sh)
This script can be used to match a timestamp of a photo (exiftool -b -DateTimeOriginal) to a time in a GPX files trkpt `<trkpt lat="69.443265" lon="26.265023"><ele>317.0</ele><time>2024-08-13T10:49:06Z</time></trkpt` effectively giving my Sony RX100 III location tagging capabilities via my Suunto Ambit3 Peak. It currently outputs gpx file with wpt's that know which photos were taken near it:

```
<wpt lat="69.908713" lon="27.00171">
    <ele>221.0</ele>
    <desc>
        <![CDATA[
        <div class="image-grid"><a href="photos/DSC03803.jpg" target="_blank"><img src="photos/DSC03803.jpg"></a>
</div>]]></desc><sym>Photo</sym></wpt>
```

The 'wpt' contains a link to the photo so it can be displayed for instance on a Leaflet map.

### How
```
./createPhotoTrack.sh <PHOTO_DIR> <GPX_PATH>
  <PHOTO_DIR> : Directory containing the photos
  <GPX_PATH>  : Directory containing GPX files or a single GPX file
```


### Requirements
- `exiftool` in $PATH
- `xmlstarlet` in $PATH
- macOs (usage of `date` is platform specific)

### TODO
- My camera time was out of sync during the trip. By 35 minutes. So a _hardcoded_ offset of +0353 is currently coded to the script. This should be made configurable.
```
    # Extract the timestamp from the photo and convert it to UTC
    timestamp=$(date -u -j -f "%Y:%m:%d %H:%M:%S%z" "$(exiftool -b -DateTimeOriginal "$photo")+0353" "+%Y-%m-%dT%H:%M:%SZ")
```
- Make usage of `date` less platform specific

## Merge sensor readings into a track (mergeSensorGpx.py)
A standalone logger - a Kestrel DROP on the outside of my pack, say - records temperature on its own clock and has no idea where it was. The GPX track knows where I was and nothing about the weather. This script joins the two on time and writes the result as a Garmin `TrackPointExtension`, so the numbers travel inside the GPX itself and any tool that reads extensions can display them:

```
<trkpt lat="69.39296" lon="26.11376"><ele>281.0</ele><time>2025-07-04T08:09:18Z</time>
  <extensions><gpxtpx:TrackPointExtension><gpxtpx:atemp>13.8</gpxtpx:atemp></gpxtpx:TrackPointExtension></extensions>
</trkpt>
```

Values are interpolated linearly between the two samples either side of each trackpoint, weighted by the real timestamps, so the logging interval can be anything and may vary within one file. Nothing is extrapolated past the log's coverage, and holes wider than `--max-gap` are left empty rather than ramped across. Re-running is safe: an existing `atemp` is replaced, and any sibling extension (`gpxtpx:hr` from a chest strap, say) is left alone.

### How
```
./mergeSensorGpx.py --gpx <FILE...> --csv <FILE> --tz <ZONE> [options]
  --gpx       : GPX file(s) to enrich, modified in place
  --csv       : sensor log export
  --tz        : timezone of the log's timestamps - an IANA name
                (Europe/Helsinki) or a fixed offset (+03:00)
  --column    : CSV column to merge (default: Temperature)
  --element   : TrackPointExtension element to write (default: atemp)
  --max-gap   : widest hole in the log to interpolate across, minutes (default: 60)
  --decimals  : decimal places to write (default: 1)
```

`--tz` is required and deliberately has no default: the Kestrel export states no UTC offset, and guessing it wrong produces temperatures that look entirely plausible while being attached to the wrong hours of the day. The run report prints both time windows so a bad guess shows up as a poor overlap.

The value is written through in whatever unit the logger recorded. The declared unit is echoed in the report but not converted, so a °F export produces °F in the GPX.

### Example
```
$ ./mergeSensorGpx.py --gpx combined.gpx \
    --csv "SandWeather_Jul_10,_2025___17_00_00.csv" --tz Europe/Helsinki

SandWeather (Kestrel DROP 2, s/n 2224283)
  column "Temperature", declared unit °C, 436 samples
  log window  2025-07-01 15:30 .. 2025-07-10 17:00 Europe/Helsinki
              2025-07-01 12:30 .. 2025-07-10 14:00 UTC

combined.gpx
  2128 trkpts: 2128 enriched, 0 outside coverage, 0 skipped (gap > 60.0 min)
  written     min 8.6  max 30.5  avg 14.6 °C
  wrote       combined.gpx
```

### One trkseg per trk
`combineGpx.sh` gives each source file its own `<trk>` rather than adding another `<trkseg>` to a shared one. This matters for anything downstream that reads extensions through [@tmcw/togeojson](https://github.com/placemark/togeojson): in 5.6.2 - still the version pinned by `@raruto/leaflet-elevation` 2.6.0 - per-segment extension arrays are indexed by the extension's position instead of the segment's, so a track with seven `trkseg`s keeps one segment's readings and nulls the rest. One `trkseg` per `trk` avoids that path entirely and parses correctly on every version.

### Requirements
- Python 3.9+ (`zoneinfo`), no third party packages
- On a slim Linux image, IANA zone names need `tzdata` installed; fixed offsets work without it

### Tests
```
python3 -m unittest discover tools
```
