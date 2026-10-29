#!/usr/bin/env python3
"""Prepare maptool --ocean-polygons for one Geofabrik extract.

Usage: prepare-ocean.py <region.poly> <output>

Ocean is cut from the global land polygons for the bounds of each outer
section of the extract's .poly. Geofabrik splits regions at the antimeridian,
so every section has west < east; latitudes are clamped to Mercator's 85°.
"""
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

LAND = 'land-polygons-split-3857/land_polygons.shp'


def sections(poly):
    boxes, coords, hole = [], None, False
    for line in poly.splitlines()[1:]:
        t = line.split()
        if not t:
            continue
        if t[0] == 'END':
            if coords and not hole:
                xs, ys = zip(*coords)
                boxes.append((max(min(xs), -180), max(min(ys), -85), min(max(xs), 180), min(max(ys), 85)))
            coords = None
        elif coords is None:
            coords, hole = [], t[0].startswith('!')
        else:
            coords.append((float(t[0]), float(t[1])))
    return [b for b in boxes if b[0] < b[2] and b[1] < b[3]]


def main():
    poly, output = sys.argv[1:]
    boxes = sections(Path(poly).read_text())
    assert boxes, 'No outer section in ' + poly
    with open(output, 'wb') as stream:
        for i, box in enumerate(boxes):
            part, start = f'{output}.{i}', time.monotonic()
            result = subprocess.run(['python3', '/usr/local/bin/coastline-polygons.py', '--land-shapefile', LAND,
                                     '--bounds=' + ','.join(map(str, box)), part],
                                    check=True, stdout=subprocess.PIPE, text=True)
            meta = json.loads(result.stdout)
            print(json.dumps(dict(bounds=box, land_records=meta['land_records'], water_polygons=meta['water_polygons'],
                                  seconds=round(time.monotonic() - start),
                                  max_rss_mb=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024)),
                  flush=True)
            stream.write(Path(part).read_bytes())
            Path(part).unlink()


if __name__ == '__main__':
    main()
