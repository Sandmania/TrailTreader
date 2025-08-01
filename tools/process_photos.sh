#!/bin/bash

set -e

usage() {
  echo "Usage: $0 [-s <source-dir>] -d <destination-dir> [-b <s3-bucket>] [--resize] [--upload] [--no-index]"
  echo "  -s <source-dir>        Directory with original JPEGs (required for --resize)"
  echo "  -d <destination-dir>   Directory to output resized images or to upload from"
  echo "  -b <s3-bucket>         (Optional) S3 bucket to upload to (required for --upload)"
  echo "  --resize               (Optional) Resize images from source to destination"
  echo "  --upload               (Optional) Upload images from destination to S3"
  echo "  --no-index             (Optional) Do not generate photos.json"
  echo "  --help                 Show this help"
  echo
  echo "Examples:"
  echo "  $0 --resize -s ./originals -d ./resized"
  echo "  $0 --upload -d ./resized -b my-bucket"
  echo "  $0 --resize --upload -s ./originals -d ./resized -b my-bucket"
  echo "  $0 -s ./originals -d ./resized -b my-bucket   # (all steps, default)"
  exit 1
}

# Step flags
DO_RESIZE=false
DO_UPLOAD=false
DO_INDEX=true
STEP_FLAG_SEEN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s) SRC="$2"; shift 2 ;;
    -d) DEST="$2"; shift 2 ;;
    -b) BUCKET="$2"; shift 2 ;;
    --resize) DO_RESIZE=true; STEP_FLAG_SEEN=true; shift ;;
    --upload) DO_UPLOAD=true; STEP_FLAG_SEEN=true; shift ;;
    --no-index) DO_INDEX=false; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

# If no step flags, do all steps (backward compatible)
if [ "$STEP_FLAG_SEEN" = false ]; then
  DO_RESIZE=true
  DO_UPLOAD=true
  DO_INDEX=true
fi

# Validate required arguments
if [ "$DO_RESIZE" = true ] && { [ -z "$SRC" ] || [ -z "$DEST" ]; }; then
  echo "Error: --resize requires -s <source-dir> and -d <destination-dir>"
  usage
fi
if [ "$DO_UPLOAD" = true ] && { [ -z "$DEST" ] || [ -z "$BUCKET" ]; }; then
  echo "Error: --upload requires -d <destination-dir> and -b <s3-bucket>"
  usage
fi
if [ "$DO_RESIZE" = false ] && [ "$DO_UPLOAD" = false ] && [ "$DO_INDEX" = true ] && [ -z "$DEST" ]; then
  echo "Error: --index (default) requires -d <destination-dir>"
  usage
fi

THUMBS="$DEST/thumbs"

# Step: Resize
if [ "$DO_RESIZE" = true ]; then
  mkdir -p "$DEST" "$THUMBS"
  echo "Resizing images to $DEST and $THUMBS..."
  cd "$SRC"
  sips -s formatOptions 98 --resampleWidth 2580 *.jpeg --out "$DEST"
  sips -s formatOptions 95 --resampleWidth 580 *.jpeg --out "$THUMBS"
  cd - >/dev/null
fi

# Step: Index
if [ "$DO_INDEX" = true ]; then
  echo "Generating $DEST/photos.json..."
  find "$DEST" -maxdepth 1 -type f -iname '*.jpeg' \
    | sed 's!.*/!!' \
    | awk '{printf "\"%s\",\n", $0}' \
    | sed '$ s/,$//' \
    | awk 'BEGIN{print "["} {print} END{print "]"}' \
    > "$DEST/photos.json"
  echo "Generated $DEST/photos.json"
fi

# Step: Upload
if [ "$DO_UPLOAD" = true ]; then
  echo "Uploading images to s3://$BUCKET/photos/..."
  aws s3 cp "$DEST" "s3://$BUCKET/photos/" --recursive --exclude "*" --include "*.jpeg"
  aws s3 cp "$THUMBS" "s3://$BUCKET/photos/thumbs/" --recursive --exclude "*" --include "*.jpeg"
  if [ "$DO_INDEX" = true ]; then
    aws s3 cp "$DEST/photos.json" "s3://$BUCKET/photos/photos.json"
  fi
  echo "Upload complete."
fi