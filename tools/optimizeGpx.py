import argparse
import math
import os
from xml.dom import minidom

EARTH_RADIUS = 6371000


def to_xy(lat, lon, lat0):
    # Local equirectangular projection in metres, accurate enough for track-sized areas
    return (math.radians(lon) * EARTH_RADIUS * math.cos(math.radians(lat0)),
            math.radians(lat) * EARTH_RADIUS)


def distance_to_segment(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def douglas_peucker(points, tolerance):
    # Returns a keep-flag per point; iterative to avoid recursion limits on long tracks
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        max_dist, max_index = 0, None
        for i in range(start + 1, end):
            d = distance_to_segment(points[i], points[start], points[end])
            if d > max_dist:
                max_dist, max_index = d, i
        if max_index is not None and max_dist > tolerance:
            keep[max_index] = True
            stack.append((start, max_index))
            stack.append((max_index, end))
    return keep


def format_number(value, decimals):
    return f"{float(value):.{decimals}f}".rstrip('0').rstrip('.')


def simplify_segments(doc, tolerance):
    for seg in doc.getElementsByTagNameNS('*', 'trkseg'):
        trkpts = seg.getElementsByTagNameNS('*', 'trkpt')
        if len(trkpts) < 3:
            continue
        lat0 = float(trkpts[0].getAttribute('lat'))
        points = [to_xy(float(p.getAttribute('lat')), float(p.getAttribute('lon')), lat0) for p in trkpts]
        for trkpt, keep in zip(trkpts, douglas_peucker(points, tolerance)):
            if not keep:
                seg.removeChild(trkpt)


def round_values(doc):
    # 6 decimals is ~10 cm, well below GPS accuracy
    for tag in ('trkpt', 'wpt', 'rtept'):
        for pt in doc.getElementsByTagNameNS('*', tag):
            for attr in ('lat', 'lon'):
                if pt.hasAttribute(attr):
                    pt.setAttribute(attr, format_number(pt.getAttribute(attr), 6))
    for ele in doc.getElementsByTagNameNS('*', 'ele'):
        if ele.firstChild is not None and ele.firstChild.nodeType == ele.TEXT_NODE:
            ele.firstChild.data = format_number(ele.firstChild.data, 1)


def strip_extensions(doc):
    for ext in doc.getElementsByTagNameNS('*', 'extensions'):
        ext.parentNode.removeChild(ext)


def strip_whitespace(node):
    # GPX has no mixed content, so whitespace-only text nodes are just formatting.
    # CDATA sections (e.g. photo descriptions) are left untouched.
    for child in list(node.childNodes):
        if child.nodeType == child.TEXT_NODE and not child.data.strip():
            node.removeChild(child)
        elif child.nodeType == child.ELEMENT_NODE:
            strip_whitespace(child)


def optimize_gpx(input_file, output_file, tolerance, remove_extensions):
    doc = minidom.parse(input_file)
    points_before = len(doc.getElementsByTagNameNS('*', 'trkpt'))

    if tolerance > 0:
        simplify_segments(doc, tolerance)
    round_values(doc)
    if remove_extensions:
        strip_extensions(doc)
    strip_whitespace(doc.documentElement)

    with open(output_file, 'w', encoding='utf-8') as f:
        doc.writexml(f, encoding='UTF-8')

    points_after = len(doc.getElementsByTagNameNS('*', 'trkpt'))
    size_before = os.path.getsize(input_file)
    size_after = os.path.getsize(output_file)
    print(f"Track points: {points_before} -> {points_after}")
    print(f"File size: {size_before / 1e6:.2f} MB -> {size_after / 1e6:.2f} MB")
    print(f"Optimized GPX file saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Reduce GPX file size by simplifying tracks (Douglas-Peucker), rounding coordinates and stripping whitespace.')
    parser.add_argument('filename', metavar='FILENAME', help='Path to the GPX file')
    parser.add_argument('-o', '--output', help='Output file (default: <FILENAME>_optimized.gpx)')
    parser.add_argument('-t', '--tolerance', type=float, default=3.0,
                        help='Max deviation from the original track in metres (default: 3, 0 disables simplification)')
    parser.add_argument('--strip-extensions', action='store_true',
                        help='Remove <extensions> elements (e.g. Garmin cadence/heart rate data)')

    args = parser.parse_args()

    output = args.output or os.path.splitext(args.filename)[0] + '_optimized.gpx'
    optimize_gpx(args.filename, output, args.tolerance, args.strip_extensions)
