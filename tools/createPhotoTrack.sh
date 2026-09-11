#!/bin/bash

# Check if the correct number of arguments is provided
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <PHOTO_DIR> <GPX_PATH> <TRIP_DIR>"
    echo "  <PHOTO_DIR> : Directory containing the photos"
    echo "  <GPX_PATH>  : Directory containing GPX files or a single GPX file"
    echo "  <TRIP_DIR>  : Trip folder used in photo links (<TRIP_DIR>/photos/ and <TRIP_DIR>/photos/thumbs/)"
    exit 1
fi

# Assign arguments to variables
PHOTO_DIR="$1"
GPX_PATH="$2"
TRIP_DIR="${3%/}"
OUTPUT_FILE="track_with_photos.gpx"

# All trackpoints from all GPX files, one per line: epoch<TAB>lat<TAB>lon<TAB>ele<TAB>time<TAB>gpx_file
TRKPT_FILE=$(mktemp "${TMPDIR:-/tmp}/trkpts.XXXXXX")
trap 'rm -f "$TRKPT_FILE"' EXIT

# Function to extract the trackpoints of a GPX file into TRKPT_FILE, converting times to epoch seconds
load_gpx() {
    local gpx_file="$1"
    echo "Loading trackpoints from $gpx_file"

    xmlstarlet sel -N x="http://www.topografix.com/GPX/1/1" -t -m "//x:trkpt" -v "concat(@lat, ',', @lon, ',', x:ele, ',', x:time)" -n "$gpx_file" |
        awk -F',' -v OFS='\t' -v file="$gpx_file" '
            # UTC "YYYY-MM-DDTHH:MM:SS[.fff]Z" to epoch seconds (days-from-civil algorithm)
            function epoch(t,   y, m, d, era, yoe, doy, doe) {
                y = substr(t, 1, 4) + 0; m = substr(t, 6, 2) + 0; d = substr(t, 9, 2) + 0
                if (m <= 2) y--
                era = int(y / 400); yoe = y - era * 400
                doy = int((153 * (m > 2 ? m - 3 : m + 9) + 2) / 5) + d - 1
                doe = yoe * 365 + int(yoe / 4) - int(yoe / 100) + doy
                return (era * 146097 + doe - 719468) * 86400 + substr(t, 12, 2) * 3600 + substr(t, 15, 2) * 60 + substr(t, 18, 2)
            }
            $4 != "" { print epoch($4), $1, $2, $3, $4, file }' >> "$TRKPT_FILE"
}

# Function to find the trackpoint closest in time to the given epoch seconds
find_closest_trkpt() {
    local target_epoch="$1"
    min_diff="" wpt_lat="" wpt_lon="" wpt_ele="" wpt_time="" closest_gpx_file=""

    IFS='|' read -r min_diff wpt_lat wpt_lon wpt_ele wpt_time closest_gpx_file < <(
        awk -F'\t' -v t="$target_epoch" '
            {
                d = $1 - t; if (d < 0) d = -d
                if (best == "" || d < best) { best = d; line = $0 }
            }
            END {
                if (best == "") exit
                split(line, f, "\t")
                print best "|" f[2] "|" f[3] "|" f[4] "|" f[5] "|" f[6]
            }' "$TRKPT_FILE")
}

# previous_wpt_time is used to see if a photo should be in the same wpt as a previous photo
previous_wpt_time=""
# Function to process a single photo
process_photo() {
    local photo="$1"
    echo "Processing photo: $photo"

    # Extract the timestamp from the photo and convert it to UTC, both as epoch seconds and ISO time
    read -r photo_epoch timestamp < <(date -u -j -f "%Y:%m:%d %H:%M:%S%z" "$(exiftool -b -DateTimeOriginal "$photo")+0309" "+%s %Y-%m-%dT%H:%M:%SZ")
    # Find the closest trkpt for this photo
    find_closest_trkpt "$photo_epoch"

    echo "For timestamp $timestamp the closest trkpt (lat=$wpt_lat lon=$wpt_lon ele=$wpt_ele time=$wpt_time) was found from $closest_gpx_file"

    # Extract the photo filename
    photo_filename=$(basename "$photo")

    # Close previous wpt tag if needed
    if [ -n "$previous_wpt_time" ] && [ "$previous_wpt_time" != "$wpt_time" ]; then
        echo "</div>]]></desc><sym>Photo</sym></wpt>" >> "$OUTPUT_FILE"
    fi

    # Create the waypoint XML structure
    if { [ -z "$previous_wpt_time" ] || [ "$previous_wpt_time" != "$wpt_time" ]; } && [ -n "$wpt_lat" ] && [ -n "$wpt_lon" ] && [ -n "$wpt_ele" ]; then
        waypoint="<wpt lat=\"$wpt_lat\" lon=\"$wpt_lon\">
    <ele>$wpt_ele</ele>
    <desc>
        <![CDATA[
        <div class=\"image-grid\">"
        # Append the waypoint to the output file
        echo "$waypoint" >>"$OUTPUT_FILE"
    fi

    # Always append the photo link inside the open waypoint
    if [ -n "$wpt_lat" ] && [ -n "$wpt_lon" ] && [ -n "$wpt_ele" ]; then
        echo "<a href=\"$TRIP_DIR/photos/$photo_filename\" target=\"_blank\"><img src=\"$TRIP_DIR/photos/thumbs/$photo_filename\"></a>" >> "$OUTPUT_FILE"
    else
        echo "Warning: No valid trkpt found for photo $photo"
    fi

    previous_wpt_time=$wpt_time
}

# Load all trackpoints once
if [ -d "$GPX_PATH" ]; then
    for gpx_file in "$GPX_PATH"/*.gpx; do
        load_gpx "$gpx_file"
    done
else
    load_gpx "$GPX_PATH"
fi

found=false

for photo in "$PHOTO_DIR"/*.{jpg,jpeg}; do
    [ -e "$photo" ] || continue
    found=true
    process_photo "$photo"
done

if [ "$found" = false ]; then
    echo "Warning: No matching .jpg or .jpeg files found in $PHOTO_DIR"
fi

# Close after last photo
echo "</div>]]></desc><sym>Photo</sym></wpt>" >> "$OUTPUT_FILE"
