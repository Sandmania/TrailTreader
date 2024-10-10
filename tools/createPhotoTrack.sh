#!/bin/bash

# Check if the correct number of arguments is provided
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <PHOTO_DIR> <GPX_PATH>"
    echo "  <PHOTO_DIR> : Directory containing the photos"
    echo "  <GPX_PATH>  : Directory containing GPX files or a single GPX file"
    exit 1
fi

# Assign arguments to variables
PHOTO_DIR="$1"
GPX_PATH="$2"
OUTPUT_FILE="track_with_photos.gpx"

# Function to calculate the absolute difference between two timestamps in seconds
time_diff() {
    local t1=$(date -jf "%Y-%m-%dT%H:%M:%SZ" "$1" +%s)
    local t2=$(date -jf "%Y-%m-%dT%H:%M:%SZ" "$2" +%s)
    echo $((t1 > t2 ? t1 - t2 : t2 - t1))
}

# Initialize variables
closest_time=""
closest_trkpt=""
min_diff=""
closest_gpx_file=""

# Function to process a GPX file and find the closest trkpt
find_closest_trkpt() {
    local target_timestamp="$1"
    local gpx_file="$2"

    while IFS=',' read -r lat lon ele time; do
        # Calculate the time difference
        diff=$(time_diff "$target_timestamp" "$time")

        # Check if this is the closest match so far
        if [ -z "$min_diff" ] || [ "$diff" -lt "$min_diff" ]; then
            min_diff="$diff"
            closest_time="$time"
            closest_trkpt="<trkpt lat=\"$lat\" lon=\"$lon\"><ele>$ele</ele><time>$time</time></trkpt>"
            closest_gpx_file=$gpx_file
        fi
    done < <(xmlstarlet sel -N x="http://www.topografix.com/GPX/1/1" -t -m "//x:trkpt" -v "concat(@lat, ',', @lon, ',', x:ele, ',', x:time)" -n "$gpx_file")
}

# previous_wpt_time is used to see if a photo should be in the same wpt as a previous photo
previous_wpt_time=""
# Function to process a single photo
process_photo() {
    local photo="$1"
    echo "Processing photo: $photo"
    min_diff=""

    # Extract the timestamp from the photo and convert it to UTC
    timestamp=$(date -u -j -f "%Y:%m:%d %H:%M:%S%z" "$(exiftool -b -DateTimeOriginal "$photo")+0353" "+%Y-%m-%dT%H:%M:%SZ")

    # Find the closest trkpt for this photo
    if [ -d "$GPX_PATH" ]; then
        for gpx_file in "$GPX_PATH"/*.gpx; do
            echo "For loopissa $timestamp $gpx_file"
            find_closest_trkpt "$timestamp" "$gpx_file"
        done
    else
        find_closest_trkpt "$timestamp" "$GPX_PATH"
    fi

    echo "For timestamp $timestamp the closest_trkpt $closest_trkpt was found from $closest_gpx_file"
    # Extract lat, lon, and ele from the closest trkpt
    wpt_lat=$(echo "$closest_trkpt" | xmlstarlet sel -t -v "trkpt/@lat")
    wpt_lon=$(echo "$closest_trkpt" | xmlstarlet sel -t -v "trkpt/@lon")
    wpt_ele=$(echo "$closest_trkpt" | xmlstarlet sel -t -v "trkpt/ele")
    wpt_time=$(echo "$closest_trkpt" | xmlstarlet sel -t -v "trkpt/time")

    # Extract the photo filename
    photo_filename=$(basename "$photo")

    # Close previous wpt tag because:
    # - previous_wpt_time is not empty, so this is not our first photo
    # - previous_wpt_time and wpt_time differ, so this round should star
    if [ -n "$previous_wpt_time" ] && [ "$previous_wpt_time" != "$wpt_time" ]; then
        echo "</div>]]></desc><sym>Photo</sym></wpt>" >> "$OUTPUT_FILE"
    else
        echo "<a href=\"photos/$photo_filename\" target=\"_blank\"><img src=\"photos/$photo_filename\"></a>" >> "$OUTPUT_FILE"
    fi

    # Create the waypoint XML structure
    if { [ -z "$previous_wpt_time" ] || [ "$previous_wpt_time" != "$wpt_time" ]; } && [ -n "$wpt_lat" ] && [ -n "$wpt_lon" ] && [ -n "$wpt_ele" ]; then
        waypoint="<wpt lat=\"$wpt_lat\" lon=\"$wpt_lon\">
    <ele>$wpt_ele</ele>
    <desc>
        <![CDATA[
        <div class=\"image-grid\"><a href=\"photos/$photo_filename\" target=\"_blank\"><img src=\"photos/$photo_filename\"></a>"

        # Append the waypoint to the output file
        echo "$waypoint" >>"$OUTPUT_FILE"
    else
        echo "Warning: No valid trkpt found for photo $photo"
    fi

    previous_wpt_time=$wpt_time
}

# Process each photo
for photo in "$PHOTO_DIR"/*.jpg; do
    process_photo "$photo"
done

# Close after last photo
echo "</div>]]></desc><sym>Photo</sym></wpt>" >> "$OUTPUT_FILE"
