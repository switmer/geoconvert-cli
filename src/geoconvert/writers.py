"""
Writers - Convert GeoJSON to various geospatial formats.
"""

import csv
import json
import sys
from pathlib import Path
from typing import Optional, Union, TextIO

# Text formats that support streaming
TEXT_FORMATS = {'.geojson', '.json', '.kml', '.gpx', '.csv', '.wkt', '.topojson'}
BINARY_FORMATS = {'.shp', '.kmz'}  # File-only formats


def write_geojson(geojson: dict, path_or_stream: Union[str, Path, TextIO], indent: int = 2, quiet: bool = False):
    """
    Write GeoJSON to file or stream.

    Args:
        geojson: GeoJSON FeatureCollection dict
        path_or_stream: Output file path, or file-like object
        indent: JSON indentation (default 2, use None for compact)
        quiet: Suppress status messages
    """
    if hasattr(path_or_stream, 'write'):
        # It's a file-like object (stream)
        json.dump(geojson, path_or_stream, indent=indent)
    else:
        with open(path_or_stream, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, indent=indent)
        if not quiet:
            print(f"Wrote {len(geojson.get('features', []))} features to {Path(path_or_stream).name}", file=sys.stderr)


def write_kml(geojson: dict, path_or_stream: Union[str, Path, TextIO], name_field: str = 'name', quiet: bool = False):
    """
    Write GeoJSON as KML file or stream.

    Args:
        geojson: GeoJSON FeatureCollection dict
        path_or_stream: Output file path, or file-like object
        name_field: Property field to use for placemark names
        quiet: Suppress status messages
    """
    is_stream = hasattr(path_or_stream, 'write')
    doc_name = "stream" if is_stream else Path(path_or_stream).stem

    def escape_xml(text) -> str:
        if not isinstance(text, str):
            text = str(text)
        return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    def coords_to_kml(coords: list) -> str:
        return " ".join(f"{lon},{lat},0" for lon, lat in coords)

    def geometry_to_kml(geometry: dict) -> str:
        geom_type = geometry.get("type")
        coords = geometry.get("coordinates", [])

        if geom_type == "Point":
            return f"<Point><coordinates>{coords[0]},{coords[1]},0</coordinates></Point>"

        elif geom_type == "LineString":
            return f"<LineString><coordinates>{coords_to_kml(coords)}</coordinates></LineString>"

        elif geom_type == "Polygon":
            parts = ["<Polygon>"]
            parts.append(f"<outerBoundaryIs><LinearRing><coordinates>{coords_to_kml(coords[0])}</coordinates></LinearRing></outerBoundaryIs>")
            for ring in coords[1:]:
                parts.append(f"<innerBoundaryIs><LinearRing><coordinates>{coords_to_kml(ring)}</coordinates></LinearRing></innerBoundaryIs>")
            parts.append("</Polygon>")
            return "".join(parts)

        elif geom_type == "MultiPoint":
            points = "".join(f"<Point><coordinates>{lon},{lat},0</coordinates></Point>" for lon, lat in coords)
            return f"<MultiGeometry>{points}</MultiGeometry>"

        elif geom_type == "MultiLineString":
            lines = "".join(f"<LineString><coordinates>{coords_to_kml(line)}</coordinates></LineString>" for line in coords)
            return f"<MultiGeometry>{lines}</MultiGeometry>"

        elif geom_type == "MultiPolygon":
            polygons = []
            for poly_coords in coords:
                parts = ["<Polygon>"]
                parts.append(f"<outerBoundaryIs><LinearRing><coordinates>{coords_to_kml(poly_coords[0])}</coordinates></LinearRing></outerBoundaryIs>")
                for ring in poly_coords[1:]:
                    parts.append(f"<innerBoundaryIs><LinearRing><coordinates>{coords_to_kml(ring)}</coordinates></LinearRing></innerBoundaryIs>")
                parts.append("</Polygon>")
                polygons.append("".join(parts))
            return f"<MultiGeometry>{''.join(polygons)}</MultiGeometry>"

        return ""

    placemarks = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})

        name = props.get(name_field, props.get("name", props.get("FIELD", "Unnamed")))
        desc_lines = [f"<b>{escape_xml(k)}:</b> {escape_xml(v)}" for k, v in props.items() if v]
        description = "<br/>".join(desc_lines)

        kml_geom = geometry_to_kml(geometry)

        placemarks.append(f"""<Placemark>
<name>{escape_xml(name)}</name>
<description><![CDATA[{description}]]></description>
{kml_geom}
</Placemark>""")

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>{escape_xml(doc_name)}</name>
<Style id="defaultStyle">
<LineStyle><color>ff0000ff</color><width>2</width></LineStyle>
<PolyStyle><color>4d0000ff</color><fill>1</fill><outline>1</outline></PolyStyle>
</Style>
{''.join(placemarks)}
</Document>
</kml>"""

    if is_stream:
        path_or_stream.write(kml)
    else:
        with open(path_or_stream, 'w', encoding='utf-8') as f:
            f.write(kml)
        if not quiet:
            print(f"Wrote {len(placemarks)} features to {Path(path_or_stream).name}", file=sys.stderr)


def write_csv(geojson: dict, path_or_stream: Union[str, Path, TextIO], include_wkt: bool = False, quiet: bool = False):
    """
    Write GeoJSON as CSV file or stream.

    For point data, includes lat/lon columns.
    For all geometries, optionally includes WKT.

    Args:
        geojson: GeoJSON FeatureCollection dict
        quiet: Suppress status messages
        path: Output file path
        include_wkt: Include WKT geometry column
    """
    features = geojson.get("features", [])
    if not features:
        print("No features to write")
        return

    # Collect all property keys
    all_keys = set()
    for f in features:
        all_keys.update(f.get("properties", {}).keys())
    all_keys = sorted(all_keys)

    # Build fieldnames
    fieldnames = list(all_keys) + ['latitude', 'longitude']
    if include_wkt:
        fieldnames.append('wkt')

    def write_rows(f):
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for feature in features:
            row = dict(feature.get("properties", {}))
            geometry = feature.get("geometry", {})

            # Get centroid for lat/lon
            centroid = _get_centroid(geometry)
            if centroid:
                row['longitude'] = centroid[0]
                row['latitude'] = centroid[1]

            if include_wkt:
                row['wkt'] = geometry_to_wkt(geometry)

            writer.writerow(row)

    is_stream = hasattr(path_or_stream, 'write')
    if is_stream:
        write_rows(path_or_stream)
    else:
        with open(path_or_stream, 'w', encoding='utf-8', newline='') as f:
            write_rows(f)
        if not quiet:
            print(f"Wrote {len(features)} features to {Path(path_or_stream).name}", file=sys.stderr)


def _get_centroid(geometry: dict) -> Optional[list]:
    """Calculate centroid of a geometry."""
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates", [])

    if geom_type == "Point":
        return coords

    elif geom_type == "LineString":
        if coords:
            mid = len(coords) // 2
            return coords[mid]

    elif geom_type == "Polygon":
        if coords and coords[0]:
            ring = coords[0]
            lon = sum(c[0] for c in ring) / len(ring)
            lat = sum(c[1] for c in ring) / len(ring)
            return [lon, lat]

    elif geom_type == "MultiPoint":
        if coords:
            lon = sum(c[0] for c in coords) / len(coords)
            lat = sum(c[1] for c in coords) / len(coords)
            return [lon, lat]

    elif geom_type == "MultiLineString":
        all_points = [p for line in coords for p in line]
        if all_points:
            lon = sum(c[0] for c in all_points) / len(all_points)
            lat = sum(c[1] for c in all_points) / len(all_points)
            return [lon, lat]

    elif geom_type == "MultiPolygon":
        all_points = [p for poly in coords for ring in poly for p in ring]
        if all_points:
            lon = sum(c[0] for c in all_points) / len(all_points)
            lat = sum(c[1] for c in all_points) / len(all_points)
            return [lon, lat]

    return None


def geometry_to_wkt(geometry: dict) -> str:
    """
    Convert GeoJSON geometry to WKT string.

    Args:
        geometry: GeoJSON geometry dict

    Returns:
        WKT string representation
    """
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates", [])

    def format_point(c):
        return f"{c[0]} {c[1]}"

    def format_ring(ring):
        return "(" + ", ".join(format_point(c) for c in ring) + ")"

    if geom_type == "Point":
        return f"POINT ({format_point(coords)})"

    elif geom_type == "LineString":
        return f"LINESTRING {format_ring(coords)}"

    elif geom_type == "Polygon":
        rings = ", ".join(format_ring(ring) for ring in coords)
        return f"POLYGON ({rings})"

    elif geom_type == "MultiPoint":
        points = ", ".join(f"({format_point(c)})" for c in coords)
        return f"MULTIPOINT ({points})"

    elif geom_type == "MultiLineString":
        lines = ", ".join(format_ring(line) for line in coords)
        return f"MULTILINESTRING ({lines})"

    elif geom_type == "MultiPolygon":
        polygons = ", ".join("(" + ", ".join(format_ring(ring) for ring in poly) + ")" for poly in coords)
        return f"MULTIPOLYGON ({polygons})"

    elif geom_type == "GeometryCollection":
        geoms = ", ".join(geometry_to_wkt(g) for g in geometry.get("geometries", []))
        return f"GEOMETRYCOLLECTION ({geoms})"

    return ""


def write_wkt(geojson: dict, path_or_stream: Union[str, Path, TextIO], quiet: bool = False):
    """
    Write GeoJSON as WKT file or stream (one geometry per line).

    Args:
        geojson: GeoJSON FeatureCollection dict
        path_or_stream: Output file path, or file-like object
        quiet: Suppress status messages
    """
    features = geojson.get("features", [])

    def write_lines(f):
        for feature in features:
            props = feature.get("properties", {})
            geometry = feature.get("geometry", {})

            wkt = geometry_to_wkt(geometry)
            name = props.get("name", props.get("FIELD", ""))

            if name:
                f.write(f"# {name}\n")
            f.write(f"{wkt}\n")

    is_stream = hasattr(path_or_stream, 'write')
    if is_stream:
        write_lines(path_or_stream)
    else:
        with open(path_or_stream, 'w', encoding='utf-8') as f:
            write_lines(f)
        if not quiet:
            print(f"Wrote {len(features)} geometries to {Path(path_or_stream).name}", file=sys.stderr)


def write_shapefile(geojson: dict, path: Union[str, Path]):
    """
    Write GeoJSON as Shapefile.

    Args:
        geojson: GeoJSON FeatureCollection dict
        path: Output file path (.shp)
    """
    import shapefile

    features = geojson.get("features", [])
    if not features:
        print("No features to write")
        return

    # Determine geometry type
    geom_types = set(f.get("geometry", {}).get("type") for f in features)
    geom_types.discard(None)

    if not geom_types:
        print("No valid geometries found")
        return

    # Map to shapefile types
    type_map = {
        "Point": shapefile.POINT,
        "MultiPoint": shapefile.MULTIPOINT,
        "LineString": shapefile.POLYLINE,
        "MultiLineString": shapefile.POLYLINE,
        "Polygon": shapefile.POLYGON,
        "MultiPolygon": shapefile.POLYGON,
    }

    # Use first valid type
    shp_type = None
    for gt in geom_types:
        if gt in type_map:
            shp_type = type_map[gt]
            break

    if not shp_type:
        print(f"Unsupported geometry type(s): {geom_types}")
        return

    # Collect all property keys and determine types
    all_keys = {}
    for f in features:
        for k, v in f.get("properties", {}).items():
            if k not in all_keys:
                if isinstance(v, int):
                    all_keys[k] = 'N'
                elif isinstance(v, float):
                    all_keys[k] = 'F'
                else:
                    all_keys[k] = 'C'

    with shapefile.Writer(str(path)) as w:
        w.shapeType = shp_type

        # Add fields (shapefile field names limited to 10 chars)
        for key, dtype in all_keys.items():
            field_name = key[:10]
            if dtype == 'N':
                w.field(field_name, 'N', 20, 0)
            elif dtype == 'F':
                w.field(field_name, 'F', 20, 10)
            else:
                w.field(field_name, 'C', 254)

        # Add features
        for feature in features:
            geom = feature.get("geometry", {})
            geom_type = geom.get("type")
            coords = geom.get("coordinates", [])

            # Write geometry
            if geom_type == "Point":
                w.point(*coords)
            elif geom_type == "MultiPoint":
                w.multipoint(coords)
            elif geom_type == "LineString":
                w.line([coords])
            elif geom_type == "MultiLineString":
                w.line(coords)
            elif geom_type == "Polygon":
                w.poly(coords)
            elif geom_type == "MultiPolygon":
                all_rings = [ring for poly in coords for ring in poly]
                w.poly(all_rings)
            else:
                continue

            # Write record
            props = feature.get("properties", {})
            record = [props.get(k[:10], None) for k in all_keys.keys()]
            w.record(*record)

    print(f"Wrote {len(features)} features to {Path(path).name}")


def write_svg(geojson: dict, path_or_stream: Union[str, Path, TextIO], width: int = 800, height: int = 600,
              stroke: str = "#ff0000", fill: str = "#ff000033", stroke_width: float = 1.0, quiet: bool = False):
    """
    Write GeoJSON as SVG file or stream.

    Args:
        geojson: GeoJSON FeatureCollection dict
        path_or_stream: Output file path, or file-like object
        width: SVG width in pixels
        height: SVG height in pixels
        stroke: Stroke color (CSS color)
        fill: Fill color (CSS color)
        stroke_width: Stroke width
        quiet: Suppress status messages
    """
    features = geojson.get("features", [])
    if not features:
        print("No features to write")
        return

    # Calculate bounding box
    min_lon, min_lat = float('inf'), float('inf')
    max_lon, max_lat = float('-inf'), float('-inf')

    def update_bounds(coords):
        nonlocal min_lon, min_lat, max_lon, max_lat
        if isinstance(coords[0], (int, float)):
            min_lon = min(min_lon, coords[0])
            max_lon = max(max_lon, coords[0])
            min_lat = min(min_lat, coords[1])
            max_lat = max(max_lat, coords[1])
        else:
            for c in coords:
                update_bounds(c)

    for feature in features:
        geom = feature.get("geometry", {})
        if geom and "coordinates" in geom:
            update_bounds(geom["coordinates"])

    if min_lon == float('inf'):
        print("No valid coordinates found")
        return

    # Calculate scale and offset
    data_width = max_lon - min_lon
    data_height = max_lat - min_lat

    if data_width == 0 or data_height == 0:
        print("Invalid bounds")
        return

    scale = min(width / data_width, height / data_height) * 0.9
    offset_x = (width - data_width * scale) / 2
    offset_y = (height - data_height * scale) / 2

    def transform(lon, lat):
        x = (lon - min_lon) * scale + offset_x
        y = height - ((lat - min_lat) * scale + offset_y)
        return x, y

    def coords_to_path(coords, close=False):
        if not coords:
            return ""
        points = [transform(c[0], c[1]) for c in coords]
        d = f"M {points[0][0]},{points[0][1]}"
        for p in points[1:]:
            d += f" L {p[0]},{p[1]}"
        if close:
            d += " Z"
        return d

    def geometry_to_svg_path(geometry: dict) -> str:
        geom_type = geometry.get("type")
        coords = geometry.get("coordinates", [])

        if geom_type == "Point":
            x, y = transform(coords[0], coords[1])
            return f'<circle cx="{x}" cy="{y}" r="3" fill="{stroke}"/>'

        elif geom_type == "LineString":
            return f'<path d="{coords_to_path(coords)}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}"/>'

        elif geom_type == "Polygon":
            d = coords_to_path(coords[0], close=True)
            for ring in coords[1:]:
                d += " " + coords_to_path(ring, close=True)
            return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" fill-rule="evenodd"/>'

        elif geom_type == "MultiPoint":
            circles = []
            for c in coords:
                x, y = transform(c[0], c[1])
                circles.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{stroke}"/>')
            return "\n".join(circles)

        elif geom_type == "MultiLineString":
            paths = [f'<path d="{coords_to_path(line)}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}"/>' for line in coords]
            return "\n".join(paths)

        elif geom_type == "MultiPolygon":
            paths = []
            for poly in coords:
                d = coords_to_path(poly[0], close=True)
                for ring in poly[1:]:
                    d += " " + coords_to_path(ring, close=True)
                paths.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" fill-rule="evenodd"/>')
            return "\n".join(paths)

        return ""

    elements = []
    for feature in features:
        geom = feature.get("geometry", {})
        if geom:
            elements.append(geometry_to_svg_path(geom))

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="white"/>
{chr(10).join(elements)}
</svg>"""

    is_stream = hasattr(path_or_stream, 'write')
    if is_stream:
        path_or_stream.write(svg)
    else:
        with open(path_or_stream, 'w', encoding='utf-8') as f:
            f.write(svg)
        if not quiet:
            print(f"Wrote {len(features)} features to {Path(path_or_stream).name}", file=sys.stderr)


def write_topojson(geojson: dict, path_or_stream: Union[str, Path, TextIO], quantization: int = 10000, quiet: bool = False):
    """
    Write GeoJSON as TopoJSON file or stream.

    Note: This is a basic implementation without shared arc detection.

    Args:
        geojson: GeoJSON FeatureCollection dict
        path_or_stream: Output file path, or file-like object
        quantization: Quantization factor for coordinate precision
        quiet: Suppress status messages
    """
    is_stream = hasattr(path_or_stream, 'write')
    obj_name = "data" if is_stream else Path(path_or_stream).stem
    features = geojson.get("features", [])
    if not features:
        print("No features to write")
        return

    # Calculate bounding box for quantization
    min_lon, min_lat = float('inf'), float('inf')
    max_lon, max_lat = float('-inf'), float('-inf')

    def update_bounds(coords):
        nonlocal min_lon, min_lat, max_lon, max_lat
        if isinstance(coords[0], (int, float)):
            min_lon = min(min_lon, coords[0])
            max_lon = max(max_lon, coords[0])
            min_lat = min(min_lat, coords[1])
            max_lat = max(max_lat, coords[1])
        else:
            for c in coords:
                update_bounds(c)

    for feature in features:
        geom = feature.get("geometry", {})
        if geom and "coordinates" in geom:
            update_bounds(geom["coordinates"])

    # Build transform
    kx = (max_lon - min_lon) / (quantization - 1) if max_lon != min_lon else 1
    ky = (max_lat - min_lat) / (quantization - 1) if max_lat != min_lat else 1

    transform = {
        "scale": [kx, ky],
        "translate": [min_lon, min_lat]
    }

    arcs = []

    def quantize_coord(lon, lat):
        return [round((lon - min_lon) / kx), round((lat - min_lat) / ky)]

    def coords_to_arc(coords):
        arc_idx = len(arcs)
        arc = []
        prev_x, prev_y = 0, 0
        for lon, lat in coords:
            qx, qy = quantize_coord(lon, lat)
            arc.append([qx - prev_x, qy - prev_y])
            prev_x, prev_y = qx, qy
        arcs.append(arc)
        return arc_idx

    def geometry_to_topo(geometry: dict) -> dict:
        geom_type = geometry.get("type")
        coords = geometry.get("coordinates", [])

        if geom_type == "Point":
            return {"type": "Point", "coordinates": quantize_coord(coords[0], coords[1])}

        elif geom_type == "MultiPoint":
            return {"type": "MultiPoint", "coordinates": [quantize_coord(c[0], c[1]) for c in coords]}

        elif geom_type == "LineString":
            return {"type": "LineString", "arcs": [coords_to_arc(coords)]}

        elif geom_type == "MultiLineString":
            return {"type": "MultiLineString", "arcs": [[coords_to_arc(line)] for line in coords]}

        elif geom_type == "Polygon":
            return {"type": "Polygon", "arcs": [[coords_to_arc(ring)] for ring in coords]}

        elif geom_type == "MultiPolygon":
            return {"type": "MultiPolygon", "arcs": [[[coords_to_arc(ring)] for ring in poly] for poly in coords]}

        return {"type": geom_type}

    geometries = []
    for feature in features:
        geom = feature.get("geometry", {})
        props = feature.get("properties", {})

        topo_geom = geometry_to_topo(geom)
        topo_geom["properties"] = props
        geometries.append(topo_geom)

    topojson_data = {
        "type": "Topology",
        "transform": transform,
        "arcs": arcs,
        "objects": {
            obj_name: {
                "type": "GeometryCollection",
                "geometries": geometries
            }
        }
    }

    if is_stream:
        json.dump(topojson_data, path_or_stream)
    else:
        with open(path_or_stream, 'w', encoding='utf-8') as f:
            json.dump(topojson_data, f)
        if not quiet:
            print(f"Wrote {len(features)} features to {Path(path_or_stream).name}", file=sys.stderr)


# Registry of writers by file extension
WRITERS = {
    '.geojson': write_geojson,
    '.json': write_geojson,
    '.kml': write_kml,
    '.csv': write_csv,
    '.wkt': write_wkt,
    '.shp': write_shapefile,
    '.svg': write_svg,
    '.topojson': write_topojson,
}
