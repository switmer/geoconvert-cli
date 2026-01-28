"""
Coordinate Reference System (CRS) handling and reprojection.
"""

from pathlib import Path
from typing import Optional, Union, List, Any

from pyproj import CRS, Transformer

# Standard CRS constants
WGS84 = "EPSG:4326"


def parse_prj_file(shp_path: Union[str, Path]) -> Optional[str]:
    """
    Parse the .prj file associated with a shapefile.

    Args:
        shp_path: Path to .shp file

    Returns:
        CRS string (WKT or EPSG code) or None if .prj doesn't exist
    """
    prj_path = Path(shp_path).with_suffix('.prj')

    if not prj_path.exists():
        return None

    try:
        with open(prj_path, 'r', encoding='utf-8') as f:
            wkt = f.read().strip()

        if not wkt:
            return None

        # Parse WKT to get a normalized CRS
        crs = CRS.from_wkt(wkt)
        return crs.to_string()

    except Exception:
        return None


def normalize_crs(crs_input: Optional[str]) -> Optional[CRS]:
    """
    Normalize a CRS string to a pyproj CRS object.

    Accepts:
        - EPSG codes: "EPSG:4326", "4326"
        - WKT strings
        - Proj4 strings
        - None (returns None)

    Args:
        crs_input: CRS string in any format

    Returns:
        pyproj CRS object or None
    """
    if not crs_input:
        return None

    try:
        # Handle bare EPSG numbers
        if crs_input.isdigit():
            crs_input = f"EPSG:{crs_input}"

        return CRS.from_user_input(crs_input)
    except Exception:
        return None


def crs_is_geographic(crs: CRS) -> bool:
    """Check if CRS is geographic (lat/lon) vs projected (meters/feet)."""
    return crs.is_geographic


def get_crs_name(crs: Optional[CRS]) -> str:
    """Get a human-readable name for the CRS."""
    if crs is None:
        return "Unknown"

    try:
        # Try to get EPSG code first
        epsg = crs.to_epsg()
        if epsg:
            return f"EPSG:{epsg}"

        # Fall back to name
        return crs.name or "Unknown"
    except Exception:
        return "Unknown"


def create_transformer(src_crs: CRS, dst_crs: CRS) -> Optional[Transformer]:
    """
    Create a coordinate transformer between two CRS.

    Args:
        src_crs: Source CRS
        dst_crs: Destination CRS

    Returns:
        Transformer object or None if CRS are equivalent
    """
    if src_crs.equals(dst_crs):
        return None

    # always_xy=True ensures (lon, lat) order, not (lat, lon)
    return Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def transform_coords(coords: List[float], transformer: Transformer) -> List[float]:
    """
    Transform a single coordinate pair/triple.

    Args:
        coords: [x, y] or [x, y, z]
        transformer: pyproj Transformer

    Returns:
        Transformed coordinates, preserving Z if present
    """
    x, y = coords[0], coords[1]
    new_x, new_y = transformer.transform(x, y)

    if len(coords) > 2:
        # Preserve Z value unchanged
        return [new_x, new_y, coords[2]]

    return [new_x, new_y]


def transform_geometry(geometry: dict, transformer: Transformer) -> dict:
    """
    Transform all coordinates in a GeoJSON geometry.

    Args:
        geometry: GeoJSON geometry dict
        transformer: pyproj Transformer

    Returns:
        New geometry dict with transformed coordinates
    """
    if not geometry or not transformer:
        return geometry

    geom_type = geometry.get("type")

    if geom_type == "Point":
        return {
            "type": "Point",
            "coordinates": transform_coords(geometry["coordinates"], transformer)
        }

    elif geom_type == "MultiPoint":
        return {
            "type": "MultiPoint",
            "coordinates": [transform_coords(c, transformer) for c in geometry["coordinates"]]
        }

    elif geom_type == "LineString":
        return {
            "type": "LineString",
            "coordinates": [transform_coords(c, transformer) for c in geometry["coordinates"]]
        }

    elif geom_type == "MultiLineString":
        return {
            "type": "MultiLineString",
            "coordinates": [
                [transform_coords(c, transformer) for c in line]
                for line in geometry["coordinates"]
            ]
        }

    elif geom_type == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [
                [transform_coords(c, transformer) for c in ring]
                for ring in geometry["coordinates"]
            ]
        }

    elif geom_type == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [transform_coords(c, transformer) for c in ring]
                    for ring in poly
                ]
                for poly in geometry["coordinates"]
            ]
        }

    elif geom_type == "GeometryCollection":
        return {
            "type": "GeometryCollection",
            "geometries": [
                transform_geometry(g, transformer) for g in geometry.get("geometries", [])
            ]
        }

    # Unknown type, return as-is
    return geometry


def transform_geojson(geojson: dict, transformer: Transformer) -> dict:
    """
    Transform all geometries in a GeoJSON FeatureCollection.

    Args:
        geojson: GeoJSON FeatureCollection dict
        transformer: pyproj Transformer

    Returns:
        New GeoJSON with transformed coordinates
    """
    if not transformer:
        return geojson

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": feature.get("properties", {}),
                "geometry": transform_geometry(feature.get("geometry", {}), transformer)
            }
            for feature in geojson.get("features", [])
        ]
    }


def requires_wgs84(output_format: str) -> bool:
    """
    Check if an output format requires WGS84 coordinates.

    Args:
        output_format: File extension (e.g., '.kml')

    Returns:
        True if format requires WGS84
    """
    # KML always requires WGS84 (Google Earth assumes it)
    # CSV with lat/lon columns should be WGS84 for most use cases
    return output_format.lower() in {'.kml', '.kmz'}


def detect_crs_from_geojson(geojson: dict) -> Optional[str]:
    """
    Detect CRS from GeoJSON if specified (deprecated but sometimes present).

    Args:
        geojson: GeoJSON dict

    Returns:
        CRS string or None
    """
    crs_obj = geojson.get("crs")
    if not crs_obj:
        return None

    props = crs_obj.get("properties", {})

    # Handle named CRS
    if crs_obj.get("type") == "name":
        name = props.get("name", "")
        # Common formats: "urn:ogc:def:crs:EPSG::4326", "EPSG:4326"
        if "EPSG" in name:
            # Extract EPSG code
            parts = name.split(":")
            for i, part in enumerate(parts):
                if part == "EPSG" and i + 1 < len(parts):
                    code = parts[-1]  # Last part after EPSG
                    if code.isdigit():
                        return f"EPSG:{code}"

    return None
