# Test Fixtures

Each fixture tests a specific conversion scenario. Tests assert:
- Feature count stability
- Bbox sanity (coordinates in expected range)
- Centroid within tolerance of expected
- Geometry types preserved correctly

## Required Fixtures

### 1. `shp_utm_polygon/`
**Purpose**: Test reprojection from projected CRS to WGS84
- Input: Shapefile in UTM Zone 15N (EPSG:26915) or similar projected CRS
- Contains: 1-3 polygons with known centroids
- Test: Convert to KML, verify centroid lands in expected lat/lon range (not UTM coords)
- Expected centroid: ~42°N, ~92°W (Iowa)

### 2. `shp_wgs84_polygon/`
**Purpose**: Test WGS84 passthrough (no reprojection needed)
- Input: Shapefile already in WGS84 (EPSG:4326)
- Contains: Polygon with hole (tests ring handling)
- Test: Convert to KML, verify no reprojection message, coordinates unchanged

### 3. `kml_placemarks/`
**Purpose**: Test KML reading with mixed content
- Input: KML with Point, LineString, Polygon placemarks
- Contains: Styles (should be dropped), ExtendedData (should be preserved)
- Test: Convert to GeoJSON, verify feature count, properties preserved

### 4. `csv_points/`
**Purpose**: Test CSV coordinate parsing with various column names
- Input: CSV with latitude/longitude columns (non-standard names)
- Contains: 5-10 points with known coordinates
- Test: Convert to GeoJSON with --lat/--lon flags, verify point positions

### 5. `topojson_counties/`
**Purpose**: Test TopoJSON arc decoding
- Input: TopoJSON with shared arcs (simplified county boundaries)
- Contains: 2-3 adjacent polygons
- Test: Convert to GeoJSON, verify feature count, topology decoded correctly

### 6. `gpx_track/`
**Purpose**: Test GPX track/waypoint parsing
- Input: GPX with track segments and waypoints
- Contains: 1 track with 2 segments, 3 waypoints
- Test: Convert to GeoJSON, verify LineString for track, Points for waypoints

## Fixture File Structure

Each fixture directory contains:
```
fixture_name/
├── input.{shp,kml,csv,gpx,topojson}  # Input file(s)
├── input.prj                          # For shapefiles
├── expected.json                      # Expected output metadata
└── README.md                          # Fixture-specific notes
```

## expected.json Format

```json
{
  "feature_count": 3,
  "geometry_types": ["Polygon", "MultiPolygon"],
  "expected_centroid": {
    "lon": -92.05,
    "lat": 42.15,
    "tolerance_degrees": 0.1
  },
  "expected_bbox": {
    "min_lon": -93.0,
    "max_lon": -91.0,
    "min_lat": 41.0,
    "max_lat": 43.0
  },
  "properties_preserved": ["name", "id"],
  "crs_input": "EPSG:26915",
  "crs_output": "EPSG:4326"
}
```

## Running Tests

```bash
pytest tests/ -v
pytest tests/test_batch.py -v  # Batch mode tests only
pytest tests/ --cov=geoconvert  # With coverage
```
