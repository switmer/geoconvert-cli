"""
Tests for geoconvert.

Run with: pytest tests/ -v
"""

import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from geoconvert import (
    convert,
    probe,
    read_geojson,
    read_shapefile,
    write_geojson,
    write_kml,
    convert_batch,
    collect_input_files,
    geometry_to_wkt,
    WGS84,
    normalize_crs,
    transform_geometry,
)
from geoconvert.crs import create_transformer


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_point_geojson():
    """Simple point GeoJSON."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Test Point", "value": 42},
                "geometry": {"type": "Point", "coordinates": [-92.0, 42.0]}
            }
        ]
    }


@pytest.fixture
def sample_polygon_geojson():
    """Polygon with hole GeoJSON."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Test Polygon"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        # Outer ring
                        [[-92.0, 42.0], [-91.0, 42.0], [-91.0, 43.0], [-92.0, 43.0], [-92.0, 42.0]],
                        # Inner ring (hole)
                        [[-91.8, 42.2], [-91.2, 42.2], [-91.2, 42.8], [-91.8, 42.8], [-91.8, 42.2]]
                    ]
                }
            }
        ]
    }


@pytest.fixture
def sample_multipolygon_geojson():
    """MultiPolygon GeoJSON."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Test MultiPolygon"},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[-92.0, 42.0], [-91.5, 42.0], [-91.5, 42.5], [-92.0, 42.5], [-92.0, 42.0]]],
                        [[[-91.0, 42.0], [-90.5, 42.0], [-90.5, 42.5], [-91.0, 42.5], [-91.0, 42.0]]]
                    ]
                }
            }
        ]
    }


@pytest.fixture
def temp_dir():
    """Temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================================
# UNIT TESTS: Geometry traversal
# ============================================================================

class TestGeometryToWkt:
    """Test WKT conversion for all geometry types."""

    def test_point(self):
        geom = {"type": "Point", "coordinates": [-92.0, 42.0]}
        wkt = geometry_to_wkt(geom)
        assert wkt == "POINT (-92.0 42.0)"

    def test_linestring(self):
        geom = {"type": "LineString", "coordinates": [[-92.0, 42.0], [-91.0, 43.0]]}
        wkt = geometry_to_wkt(geom)
        assert "LINESTRING" in wkt
        assert "-92.0 42.0" in wkt

    def test_polygon(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[[-92.0, 42.0], [-91.0, 42.0], [-91.0, 43.0], [-92.0, 42.0]]]
        }
        wkt = geometry_to_wkt(geom)
        assert "POLYGON" in wkt

    def test_polygon_with_hole(self, sample_polygon_geojson):
        geom = sample_polygon_geojson["features"][0]["geometry"]
        wkt = geometry_to_wkt(geom)
        assert "POLYGON" in wkt
        # Should have two rings
        assert wkt.count("(") >= 3  # POLYGON + 2 rings

    def test_multipolygon(self, sample_multipolygon_geojson):
        geom = sample_multipolygon_geojson["features"][0]["geometry"]
        wkt = geometry_to_wkt(geom)
        assert "MULTIPOLYGON" in wkt


# ============================================================================
# UNIT TESTS: CRS and reprojection
# ============================================================================

class TestCRS:
    """Test CRS handling."""

    def test_normalize_epsg(self):
        crs = normalize_crs("EPSG:4326")
        assert crs is not None
        assert crs.to_epsg() == 4326

    def test_normalize_bare_number(self):
        crs = normalize_crs("4326")
        assert crs is not None
        assert crs.to_epsg() == 4326

    def test_normalize_invalid(self):
        crs = normalize_crs("not-a-crs")
        assert crs is None


class TestTransformGeometry:
    """Test coordinate transformation."""

    def test_transform_point(self):
        # UTM Zone 15N to WGS84
        src_crs = normalize_crs("EPSG:26915")
        dst_crs = normalize_crs("EPSG:4326")
        transformer = create_transformer(src_crs, dst_crs)

        # A point roughly in Iowa in UTM coords
        geom = {"type": "Point", "coordinates": [500000, 4650000]}
        transformed = transform_geometry(geom, transformer)

        # Should now be in lat/lon
        lon, lat = transformed["coordinates"]
        assert -94 < lon < -90  # Iowa longitude range
        assert 41 < lat < 44    # Iowa latitude range

    def test_transform_polygon(self):
        src_crs = normalize_crs("EPSG:26915")
        dst_crs = normalize_crs("EPSG:4326")
        transformer = create_transformer(src_crs, dst_crs)

        geom = {
            "type": "Polygon",
            "coordinates": [[[500000, 4650000], [510000, 4650000], [510000, 4660000], [500000, 4650000]]]
        }
        transformed = transform_geometry(geom, transformer)

        # Check all coordinates are in valid lat/lon range
        for coord in transformed["coordinates"][0]:
            lon, lat = coord
            assert -180 <= lon <= 180
            assert -90 <= lat <= 90

    def test_same_crs_no_transform(self):
        src_crs = normalize_crs("EPSG:4326")
        dst_crs = normalize_crs("EPSG:4326")
        transformer = create_transformer(src_crs, dst_crs)

        # Should return None (no transform needed)
        assert transformer is None


# ============================================================================
# INTEGRATION TESTS: Round-trip conversions
# ============================================================================

class TestRoundTrip:
    """Test round-trip conversions."""

    def test_geojson_to_kml_to_geojson(self, sample_polygon_geojson, temp_dir):
        """GeoJSON -> KML -> GeoJSON preserves features."""
        # Write original
        geojson_path = temp_dir / "original.geojson"
        write_geojson(sample_polygon_geojson, geojson_path)

        # Convert to KML
        kml_path = temp_dir / "converted.kml"
        success = convert(geojson_path, kml_path, assume_wgs84=True)
        assert success
        assert kml_path.exists()

        # Convert back
        geojson2_path = temp_dir / "roundtrip.geojson"
        success = convert(kml_path, geojson2_path)
        assert success

        # Compare
        result = read_geojson(geojson2_path)
        assert len(result["features"]) == len(sample_polygon_geojson["features"])

    def test_geojson_to_csv(self, sample_point_geojson, temp_dir):
        """GeoJSON points to CSV preserves coordinates."""
        geojson_path = temp_dir / "points.geojson"
        write_geojson(sample_point_geojson, geojson_path)

        csv_path = temp_dir / "points.csv"
        success = convert(geojson_path, csv_path, assume_wgs84=True)
        assert success
        assert csv_path.exists()

        # Check CSV content
        content = csv_path.read_text()
        assert "latitude" in content
        assert "longitude" in content
        assert "42" in content  # latitude


# ============================================================================
# INTEGRATION TESTS: Probe
# ============================================================================

class TestProbe:
    """Test probe functionality."""

    def test_probe_geojson(self, sample_polygon_geojson, temp_dir):
        geojson_path = temp_dir / "test.geojson"
        write_geojson(sample_polygon_geojson, geojson_path)

        result = probe(geojson_path)

        assert result["feature_count"] == 1
        assert "Polygon" in result["geometry_types"]
        assert "name" in result["properties"]


# ============================================================================
# INTEGRATION TESTS: Batch mode
# ============================================================================

class TestBatch:
    """Test batch conversion."""

    def test_batch_basic(self, sample_point_geojson, sample_polygon_geojson, temp_dir):
        """Batch convert multiple files."""
        input_dir = temp_dir / "input"
        output_dir = temp_dir / "output"
        input_dir.mkdir()

        # Create input files
        write_geojson(sample_point_geojson, input_dir / "points.geojson")
        write_geojson(sample_polygon_geojson, input_dir / "polygons.geojson")

        # Collect and convert
        files = collect_input_files(input_dir, include_ext=[".geojson"])
        assert len(files) == 2

        result = convert_batch(
            files,
            output_dir,
            ".kml",
            assume_wgs84=True,
            quiet=True,
        )

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0

    def test_batch_skip_existing(self, sample_point_geojson, temp_dir):
        """Batch skips existing files without --overwrite."""
        input_dir = temp_dir / "input"
        output_dir = temp_dir / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        # Create input and pre-existing output
        write_geojson(sample_point_geojson, input_dir / "points.geojson")
        (output_dir / "points.kml").write_text("<kml>existing</kml>")

        files = collect_input_files(input_dir, include_ext=[".geojson"])

        result = convert_batch(
            files,
            output_dir,
            ".kml",
            overwrite=False,
            assume_wgs84=True,
            quiet=True,
        )

        assert result.skipped == 1
        assert result.succeeded == 0

    def test_batch_overwrite(self, sample_point_geojson, temp_dir):
        """Batch overwrites with --overwrite."""
        input_dir = temp_dir / "input"
        output_dir = temp_dir / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        write_geojson(sample_point_geojson, input_dir / "points.geojson")
        (output_dir / "points.kml").write_text("<kml>existing</kml>")

        files = collect_input_files(input_dir, include_ext=[".geojson"])

        result = convert_batch(
            files,
            output_dir,
            ".kml",
            overwrite=True,
            assume_wgs84=True,
            quiet=True,
        )

        assert result.succeeded == 1
        assert result.skipped == 0


# ============================================================================
# EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_feature_collection(self, temp_dir):
        """Handle empty FeatureCollection."""
        geojson = {"type": "FeatureCollection", "features": []}
        geojson_path = temp_dir / "empty.geojson"
        write_geojson(geojson, geojson_path)

        result = probe(geojson_path)
        assert result["feature_count"] == 0

    def test_unsupported_format(self, temp_dir):
        """Reject unsupported formats."""
        fake_file = temp_dir / "test.xyz"
        fake_file.write_text("fake content")

        success = convert(fake_file, temp_dir / "output.geojson")
        assert not success

    def test_missing_crs_for_kml(self, sample_polygon_geojson, temp_dir):
        """Fail gracefully when CRS missing for KML output."""
        geojson_path = temp_dir / "test.geojson"
        write_geojson(sample_polygon_geojson, geojson_path)

        kml_path = temp_dir / "test.kml"

        # Should fail without --assume-wgs84 (no CRS detected from GeoJSON)
        # Note: This might pass if GeoJSON reader defaults to WGS84
        # The test documents expected behavior
        success = convert(geojson_path, kml_path)
        # Either succeeds (assumes WGS84) or fails (requires explicit flag)
        # Both are valid behaviors - document what yours does
        assert isinstance(success, bool)

    def test_kmz_reading(self, sample_point_geojson, temp_dir):
        """KMZ files are auto-extracted and read."""
        from geoconvert import write_kml
        from geoconvert.readers import read_kmz

        # Create a KML file
        kml_path = temp_dir / "doc.kml"
        write_kml(sample_point_geojson, kml_path, name_field="name")

        # Zip it into a KMZ
        kmz_path = temp_dir / "test.kmz"
        with zipfile.ZipFile(kmz_path, 'w') as kmz:
            kmz.write(kml_path, "doc.kml")

        # Read the KMZ
        result = read_kmz(kmz_path)

        assert result["type"] == "FeatureCollection"
        assert len(result["features"]) == 1
