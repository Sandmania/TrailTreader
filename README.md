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
