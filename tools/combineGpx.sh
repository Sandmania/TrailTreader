#!/bin/bash

# Output file
OUTPUT="combined.gpx"

# Initialize the combined GPX file
echo '<?xml version="1.0" encoding="UTF-8" standalone="no"?>' > $OUTPUT
echo '<gpx creator="TrailTreader Tools" xmlns="http://www.topografix.com/GPX/1/1" xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="1.1" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">' >> $OUTPUT

# Add a metadata section (you can customize this as needed)
echo '<metadata>' >> $OUTPUT
echo '    <name>Combined GPX File</name>' >> $OUTPUT
echo '</metadata>' >> $OUTPUT

# Declare a variable to hold all wpt elements
wpt_elements=""
track_segments=""
fileNro=0

# Loop over all GPX files passed as arguments
for file in "$@"
do
    fileNro=$[fileNro + 1]
    echo "Processing file: $fileNro $file"
    
    # Check if the file is a well-formed XML/GPX file
    if ! xmlstarlet val --well-formed "$file" > /dev/null 2>&1; then
        echo "Error: $file is not a well-formed XML/GPX file."
        exit 1
    fi

    # Extract trkseg content
    track_segments+=$(xmlstarlet sel -N x="http://www.topografix.com/GPX/1/1" -t -c "//x:trkseg" "$file")

    # Extract the last trkpt within the trkseg and convert it to a wpt
    last_trkpt=$(xmlstarlet sel -N x="http://www.topografix.com/GPX/1/1" -t -c "(//x:trkseg//x:trkpt)[last()]" "$file")
    
    # Debugging: print the last_trkpt XML content
    echo "Extracted last trkpt: $last_trkpt"
    
    if [ -z "$last_trkpt" ]; then
        echo "Warning: No trkpt found in $file."
        continue
    fi
    
    # Handle namespace in the extracted last_trkpt
    wpt_lat=$(echo "$last_trkpt" | xmlstarlet sel -N x="http://www.topografix.com/GPX/1/1" -t -v "x:trkpt/@lat")
    wpt_lon=$(echo "$last_trkpt" | xmlstarlet sel -N x="http://www.topografix.com/GPX/1/1" -t -v "x:trkpt/@lon")
    wpt_ele=$(echo "$last_trkpt" | xmlstarlet sel -N x="http://www.topografix.com/GPX/1/1" -t -v "x:trkpt/x:ele")
    
    # Debugging: print the extracted values
    echo "Extracted wpt_lat: $wpt_lat, wpt_lon: $wpt_lon, wpt_ele: $wpt_ele"
    
    # Append the wpt element to the wpt_elements variable
    wpt_elements+="<wpt lat=\"$wpt_lat\" lon=\"$wpt_lon\"><ele>$wpt_ele</ele><name>Leg $fileNro</name></wpt>\n"
done

# Add all the wpt elements
echo -e "$wpt_elements" >> $OUTPUT

# Prepare to collect all track segments
echo '<trk>' >> $OUTPUT
echo '<name>Combined Track</name>' >> $OUTPUT

# Add track segments
echo -e "$track_segments" >> $OUTPUT

# Close the trk element
echo '</trk>' >> $OUTPUT

# Close the gpx tag
echo '</gpx>' >> $OUTPUT

echo "Combined GPX file created: $OUTPUT"