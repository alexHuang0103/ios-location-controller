"""Create a timed straight-line GPX route for pymobiledevice3."""

import math
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

EARTH_RADIUS_M = 6_371_000
SPEED_KMH = 19.5
STEP_SECONDS = 0.5
MAX_DISTANCE_M = 200_000


def distance_m(start, end):
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    h = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1, math.sqrt(h)))


def interpolate(start, end, fraction):
    fraction = min(1, max(0, fraction))
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    first = (math.cos(lat1) * math.cos(lon1), math.cos(lat1) * math.sin(lon1), math.sin(lat1))
    last = (math.cos(lat2) * math.cos(lon2), math.cos(lat2) * math.sin(lon2), math.sin(lat2))
    angle = math.acos(max(-1, min(1, sum(a * b for a, b in zip(first, last)))))
    if angle < 1e-9:
        return start
    scale = math.sin(angle)
    left = math.sin((1 - fraction) * angle) / scale
    right = math.sin(fraction * angle) / scale
    x, y, z = (left * a + right * b for a, b in zip(first, last))
    return (math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x)))


def create_gpx(start, end):
    distance = distance_m(start, end)
    if distance < 1:
        raise ValueError('起點與終點太近，請至少相隔 1 公尺')
    if distance > MAX_DISTANCE_M:
        raise ValueError('單次移動最長 200 公里，請縮短起終點距離')
    duration = distance / (SPEED_KMH * 1000 / 3600)
    count = math.ceil(duration / STEP_SECONDS)
    now = datetime.now(timezone.utc)
    root = ET.Element('gpx', version='1.1', creator='iOS GPS 控制台',
                      xmlns='http://www.topografix.com/GPX/1/1')
    segment = ET.SubElement(ET.SubElement(root, 'trk'), 'trkseg')
    for index in range(count + 1):
        elapsed = min(index * STEP_SECONDS, duration)
        point = interpolate(start, end, elapsed / duration)
        node = ET.SubElement(segment, 'trkpt', lat=f'{point[0]:.8f}', lon=f'{point[1]:.8f}')
        ET.SubElement(node, 'time').text = (now + timedelta(seconds=elapsed)).isoformat().replace('+00:00', 'Z')
    # A final point is required when the duration is not an exact multiple of the step.
    if count * STEP_SECONDS > duration:
        last = segment[-1]
        last.set('lat', f'{end[0]:.8f}')
        last.set('lon', f'{end[1]:.8f}')
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.gpx', prefix='ios_gps_route_', delete=False) as file:
        path = Path(file.name)
        ET.ElementTree(root).write(file, encoding='utf-8', xml_declaration=True)
    return path, distance, duration
