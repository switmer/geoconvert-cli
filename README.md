# geoconvert

**Convert common geospatial files with one command.**

GeoJSON hub. KML-ready reprojection. Batch mode. Probe to avoid surprises.

```bash
pip install geoconvert-cli
geoconvert parcels.shp parcels.kml
```

---

## The problem

You have a shapefile from the county. You need KML for Google Earth. Or GeoJSON for your web map. Or CSV for a spreadsheet.

So you either:
- Fight with GDAL/ogr2ogr flags you'll forget by tomorrow
- Upload to some website and hope it doesn't mangle your data
- Open QGIS just to click Export

And then your KML shows up in the middle of the ocean because the shapefile was in State Plane and nobody told you.

---

## The fix

```bash
pip install geoconvert
```

```bash
# Single file
geoconvert input.shp output.geojson

# Batch convert a whole directory
geoconvert county_data/ converted/ --to kml

# Check what you're dealing with first
geoconvert --probe mystery_file.shp
```

That's it. It reads the `.prj`, reprojects to WGS84 when needed, and tells you when something's wrong instead of silently producing garbage.

---

## What it handles

| From | To |
|------|-----|
| Shapefile (.shp) | GeoJSON |
| GeoJSON | KML (Google Earth) |
| KML / KMZ | CSV (with lat/lon) |
| GPX (GPS tracks) | TopoJSON (for D3) |
| CSV (with coordinates) | SVG (static maps) |
| TopoJSON | WKT (for PostGIS) |
|  | Shapefile |

Mix and match. Everything goes through GeoJSON internally, so any input works with any output.

---

## What it gets right

**Projections.** If your shapefile is in UTM or State Plane, it reprojects to WGS84 automatically for formats that need it (like KML). If it can't figure out the CRS, it tells you instead of guessing.

```bash
geoconvert --probe parcels.shp

# Output:
# CRS: EPSG:26915 (UTM Zone 15N)
#   Geographic (lat/lon): No (projected)
# Features: 847
# Geometry types: MultiPolygon
#
# Warnings:
#   - CRS is projected. KML output requires reprojection.
```

**Batch mode that doesn't destroy your afternoon.** Convert hundreds of files. Skip ones that already exist. Get a JSON report of what worked and what didn't.

```bash
geoconvert all_parcels/ output/ --to kml --summary --report results.json

# Found 423 files to convert
# ...
# Batch conversion complete:
#   Succeeded: 421
#   Failed: 2
#   Skipped: 0
```

**Honest about what it drops.** KML can have styles, folders, network links, overlays. When you convert to GeoJSON, those go away. `--probe` tells you upfront.

---

## Use it as a library

```python
from geoconvert import convert, read_shapefile, write_kml, probe

# One-liner
convert("input.shp", "output.geojson")

# Or read, filter, write
geojson = read_shapefile("parcels.shp")
geojson["features"] = [f for f in geojson["features"]
                       if f["properties"]["ACRES"] > 40]
write_kml(geojson, "large_parcels.kml")

# Check a file before converting
info = probe("unknown.kml")
print(info["crs"], info["feature_count"], info["warnings"])
```

---

## Install

```bash
pip install geoconvert-cli
```

Requires Python 3.9+. Dependencies: `pyshp`, `pyproj`.

---

## CLI Reference

```
geoconvert [options] input... output

Modes:
  geoconvert in.shp out.geojson          Single file conversion
  geoconvert dir/ out/ --to kml          Batch conversion
  geoconvert --probe file.shp            Inspect without converting

Batch options:
  --to EXT              Target format (kml, geojson, csv, etc.)
  --recursive, -r       Process subdirectories
  --include-ext .shp    Only process these extensions
  --overwrite           Replace existing output files
  --summary             Print totals at end
  --report FILE         Save JSON report

CRS options:
  --src-crs EPSG:26915  Override source CRS
  --assume-wgs84        Trust input is already WGS84
  --no-reproject        Skip reprojection (advanced)

Format options:
  --lat COL             Latitude column for CSV input
  --lon COL             Longitude column for CSV input
  --name-field PROP     Property for KML placemark names
  --include-wkt         Add WKT column to CSV output
  --width, --height     SVG dimensions
```

---

## When to use something else

- **You need industrial-strength format support**: Use GDAL/ogr2ogr
- **You need topology preservation**: Use TopoJSON CLI
- **You're doing spatial analysis**: Use GeoPandas or PostGIS
- **You need a GUI**: Use QGIS

geoconvert is for the 80% case: you have files in format A, you need them in format B, and you want it to just work.

---

## What it actually supports

### Shapefiles
Works with standard Point, LineString, Polygon, Multi* geometries in WGS84 or any projected CRS with a `.prj` file. Reads DBF attributes. Field names truncate to 10 characters on output (shapefile limitation).

### KML / KMZ
Reads Placemarks with geometry and ExtendedData. KMZ files are auto-extracted. Writes standard Placemarks. Ignores NetworkLinks, GroundOverlays, Styles, and folder hierarchy.

### Everything else
- **GeoJSON**: Full support (it's the internal format)
- **GPX**: Waypoints become Points, tracks become LineStrings
- **CSV**: Points only, requires lat/lon columns
- **TopoJSON**: Basic arc decoding, no topology optimization on output
- **WKT**: Output only, one geometry per line
- **SVG**: Output only, simple styling

---

## License

MIT

---

*Built because life's too short to remember ogr2ogr flags.*
