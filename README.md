# Navit Map Server

Pre-built [Navit](https://github.com/navit-gps/navit) maps, automatically converted from [Geofabrik](https://download.geofabrik.de/) OSM extracts.

This fork builds them with a patched maptool from [pgrandin/navit `fix/water-junctions`](https://github.com/pgrandin/navit/tree/fix/water-junctions): ocean comes from prepared polygons cut from the global [OSM land polygons](https://osmdata.openstreetmap.de/data/land-polygons.html) instead of being inferred from the extract's coastline, and inland water rings are nested by geometry.

## Getting a map

Go to the [latest release](https://github.com/pgrandin/gh-actions-mapserver/releases/latest) and download the `.bin` file for your region.

Files are named `<continent>-<region>-<date>.bin`, for example:

```
europe-france-alsace-2026-03-18.bin
north-america-us-california-2026-03-18.bin
asia-japan-2026-03-18.bin
```

## Using the map in Navit

Place the downloaded `.bin` file somewhere on your device and point Navit to it in your `navit.xml`:

```xml
<mapset enabled="yes">
  <map type="binfile" enabled="yes" data="/path/to/your-region.bin"/>
</mapset>
```

## Updates

Check the [releases page](https://github.com/pgrandin/gh-actions-mapserver/releases) for the latest build for your region.
