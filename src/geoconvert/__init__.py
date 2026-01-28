"""
geoconvert - Universal Geospatial Format Converter

Convert between common geospatial formats using GeoJSON as the internal representation.

Supported formats:
    Input:  .shp, .geojson, .json, .kml, .gpx, .csv, .topojson
    Output: .geojson, .json, .kml, .csv, .wkt, .shp, .svg, .topojson

Example usage:
    from geoconvert import convert, read_shapefile, write_kml

    # Simple conversion
    convert("input.shp", "output.geojson")

    # Read to GeoJSON, manipulate, then write
    geojson = read_shapefile("farms.shp")
    geojson["features"] = [f for f in geojson["features"] if f["properties"]["area"] > 100]
    write_kml(geojson, "large_farms.kml")
"""

__version__ = "0.1.0"

from .readers import (
    read_geojson,
    read_shapefile,
    read_kml,
    read_gpx,
    read_csv,
    read_topojson,
    READERS,
)

from .writers import (
    write_geojson,
    write_kml,
    write_csv,
    write_wkt,
    write_shapefile,
    write_svg,
    write_topojson,
    geometry_to_wkt,
    WRITERS,
)

from .core import (
    convert,
    get_supported_formats,
    probe,
    print_probe_report,
    convert_batch,
    collect_input_files,
    BatchResult,
    FileResult,
)

from .crs import (
    WGS84,
    normalize_crs,
    transform_geometry,
    transform_geojson,
)

__all__ = [
    # Version
    "__version__",
    # Readers
    "read_geojson",
    "read_shapefile",
    "read_kml",
    "read_gpx",
    "read_csv",
    "read_topojson",
    "READERS",
    # Writers
    "write_geojson",
    "write_kml",
    "write_csv",
    "write_wkt",
    "write_shapefile",
    "write_svg",
    "write_topojson",
    "geometry_to_wkt",
    "WRITERS",
    # Core
    "convert",
    "get_supported_formats",
    "probe",
    "print_probe_report",
    # Batch
    "convert_batch",
    "collect_input_files",
    "BatchResult",
    "FileResult",
    # CRS
    "WGS84",
    "normalize_crs",
    "transform_geometry",
    "transform_geojson",
]
