"""
Readers - Convert various geospatial formats to GeoJSON.
"""

import csv
import json
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional, Union


def read_geojson(path: Union[str, Path]) -> dict:
    """
    Read a GeoJSON file.

    Args:
        path: Path to .geojson or .json file

    Returns:
        GeoJSON FeatureCollection dict
    """
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Normalize to FeatureCollection
    if data.get("type") == "FeatureCollection":
        return data
    elif data.get("type") == "Feature":
        return {"type": "FeatureCollection", "features": [data]}
    else:
        # Assume it's a geometry
        return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": data}]}


def read_shapefile(path: Union[str, Path], detect_crs: bool = True) -> dict:
    """
    Read a Shapefile and convert to GeoJSON.

    Args:
        path: Path to .shp file
        detect_crs: Whether to read .prj file for CRS info

    Returns:
        GeoJSON FeatureCollection dict with optional '_crs' metadata
    """
    import shapefile
    from .crs import parse_prj_file

    path = Path(path)

    with shapefile.Reader(str(path)) as shp:
        geojson = {"type": "FeatureCollection", "features": []}
        field_names = [field[0] for field in shp.fields[1:]]

        for shape_record in shp.iterShapeRecords():
            properties = dict(zip(field_names, shape_record.record))
            geometry = shape_record.shape.__geo_interface__
            geojson["features"].append({
                "type": "Feature",
                "properties": properties,
                "geometry": geometry
            })

    # Detect CRS from .prj file
    if detect_crs:
        crs = parse_prj_file(path)
        if crs:
            geojson["_crs"] = crs

    return geojson


def read_kml(path: Union[str, Path]) -> dict:
    """
    Read a KML file and convert to GeoJSON.

    Args:
        path: Path to .kml file

    Returns:
        GeoJSON FeatureCollection dict
    """
    tree = ET.parse(path)
    root = tree.getroot()

    # Handle KML namespace
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    if root.tag.startswith('{'):
        ns['kml'] = root.tag.split('}')[0][1:]

    geojson = {"type": "FeatureCollection", "features": []}

    # Find all Placemarks
    for placemark in root.iter('{%s}Placemark' % ns['kml']):
        feature = {"type": "Feature", "properties": {}, "geometry": None}

        # Extract name
        name_elem = placemark.find('kml:name', ns)
        if name_elem is not None and name_elem.text:
            feature["properties"]["name"] = name_elem.text

        # Extract description
        desc_elem = placemark.find('kml:description', ns)
        if desc_elem is not None and desc_elem.text:
            feature["properties"]["description"] = desc_elem.text

        # Extract ExtendedData
        for data in placemark.findall('.//kml:Data', ns):
            name = data.get('name')
            value_elem = data.find('kml:value', ns)
            if name and value_elem is not None:
                feature["properties"][name] = value_elem.text

        # Extract geometry
        feature["geometry"] = _parse_kml_geometry(placemark, ns)

        if feature["geometry"]:
            geojson["features"].append(feature)

    return geojson


def _parse_kml_coords(coord_text: str) -> list:
    """Parse KML coordinate string into list of [lon, lat] pairs."""
    coords = []
    for part in coord_text.strip().split():
        if part:
            values = part.split(',')
            if len(values) >= 2:
                coords.append([float(values[0]), float(values[1])])
    return coords


def _parse_kml_geometry(placemark, ns: dict) -> Optional[dict]:
    """Parse KML geometry elements into GeoJSON geometry."""
    # Point
    point = placemark.find('.//kml:Point/kml:coordinates', ns)
    if point is not None and point.text:
        coords = _parse_kml_coords(point.text)
        if coords:
            return {"type": "Point", "coordinates": coords[0]}

    # LineString
    line = placemark.find('.//kml:LineString/kml:coordinates', ns)
    if line is not None and line.text:
        coords = _parse_kml_coords(line.text)
        if coords:
            return {"type": "LineString", "coordinates": coords}

    # Polygon
    polygon = placemark.find('.//kml:Polygon', ns)
    if polygon is not None:
        rings = []
        outer = polygon.find('.//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', ns)
        if outer is not None and outer.text:
            rings.append(_parse_kml_coords(outer.text))
        for inner in polygon.findall('.//kml:innerBoundaryIs/kml:LinearRing/kml:coordinates', ns):
            if inner.text:
                rings.append(_parse_kml_coords(inner.text))
        if rings:
            return {"type": "Polygon", "coordinates": rings}

    # MultiGeometry
    multi = placemark.find('.//kml:MultiGeometry', ns)
    if multi is not None:
        geometries = []
        for child in multi:
            tag = child.tag.split('}')[-1]
            if tag == 'Point':
                coords_elem = child.find('kml:coordinates', ns)
                if coords_elem is not None and coords_elem.text:
                    coords = _parse_kml_coords(coords_elem.text)
                    if coords:
                        geometries.append({"type": "Point", "coordinates": coords[0]})
            elif tag == 'LineString':
                coords_elem = child.find('kml:coordinates', ns)
                if coords_elem is not None and coords_elem.text:
                    coords = _parse_kml_coords(coords_elem.text)
                    if coords:
                        geometries.append({"type": "LineString", "coordinates": coords})
            elif tag == 'Polygon':
                rings = []
                outer = child.find('.//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', ns)
                if outer is not None and outer.text:
                    rings.append(_parse_kml_coords(outer.text))
                for inner in child.findall('.//kml:innerBoundaryIs/kml:LinearRing/kml:coordinates', ns):
                    if inner.text:
                        rings.append(_parse_kml_coords(inner.text))
                if rings:
                    geometries.append({"type": "Polygon", "coordinates": rings})

        if geometries:
            # Convert to Multi* type if all same type
            types = set(g["type"] for g in geometries)
            if len(types) == 1:
                geom_type = list(types)[0]
                if geom_type == "Point":
                    return {"type": "MultiPoint", "coordinates": [g["coordinates"] for g in geometries]}
                elif geom_type == "LineString":
                    return {"type": "MultiLineString", "coordinates": [g["coordinates"] for g in geometries]}
                elif geom_type == "Polygon":
                    return {"type": "MultiPolygon", "coordinates": [g["coordinates"] for g in geometries]}
            return {"type": "GeometryCollection", "geometries": geometries}

    return None


def read_kmz(path: Union[str, Path]) -> dict:
    """
    Read a KMZ file (zipped KML) and convert to GeoJSON.

    Args:
        path: Path to .kmz file

    Returns:
        GeoJSON FeatureCollection dict
    """
    path = Path(path)

    with zipfile.ZipFile(path, 'r') as kmz:
        # Find the primary KML file
        kml_files = [f for f in kmz.namelist() if f.lower().endswith('.kml')]

        if not kml_files:
            return {"type": "FeatureCollection", "features": []}

        # Prefer doc.kml, otherwise take the first KML
        kml_name = 'doc.kml' if 'doc.kml' in kml_files else kml_files[0]

        # Extract to temp and read
        with tempfile.TemporaryDirectory() as tmpdir:
            kml_path = Path(tmpdir) / kml_name
            kmz.extract(kml_name, tmpdir)
            return read_kml(kml_path)


def read_gpx(path: Union[str, Path]) -> dict:
    """
    Read a GPX file and convert to GeoJSON.

    Args:
        path: Path to .gpx file

    Returns:
        GeoJSON FeatureCollection dict
    """
    tree = ET.parse(path)
    root = tree.getroot()

    # Handle GPX namespace
    ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}
    if root.tag.startswith('{'):
        ns['gpx'] = root.tag.split('}')[0][1:]

    geojson = {"type": "FeatureCollection", "features": []}

    def find_elem(parent, name):
        """Find element with or without namespace."""
        elem = parent.find(f'gpx:{name}', ns)
        if elem is None:
            elem = parent.find(name)
        return elem

    def find_all_elem(parent, name):
        """Find all elements with or without namespace."""
        elems = parent.findall(f'.//gpx:{name}', ns)
        if not elems:
            elems = parent.findall(f'.//{name}')
        return elems

    # Waypoints -> Points
    for wpt in find_all_elem(root, 'wpt'):
        lat = float(wpt.get('lat'))
        lon = float(wpt.get('lon'))

        properties = {}
        name_elem = find_elem(wpt, 'name')
        if name_elem is not None and name_elem.text:
            properties['name'] = name_elem.text

        desc_elem = find_elem(wpt, 'desc')
        if desc_elem is not None and desc_elem.text:
            properties['description'] = desc_elem.text

        ele_elem = find_elem(wpt, 'ele')
        if ele_elem is not None and ele_elem.text:
            properties['elevation'] = float(ele_elem.text)

        geojson["features"].append({
            "type": "Feature",
            "properties": properties,
            "geometry": {"type": "Point", "coordinates": [lon, lat]}
        })

    # Tracks -> LineStrings
    for trk in find_all_elem(root, 'trk'):
        properties = {}
        name_elem = find_elem(trk, 'name')
        if name_elem is not None and name_elem.text:
            properties['name'] = name_elem.text

        # Collect all track segments
        all_coords = []
        for trkseg in find_all_elem(trk, 'trkseg'):
            coords = []
            for trkpt in trkseg.findall('gpx:trkpt', ns) or trkseg.findall('trkpt'):
                lat = float(trkpt.get('lat'))
                lon = float(trkpt.get('lon'))
                coords.append([lon, lat])
            if coords:
                all_coords.append(coords)

        if len(all_coords) == 1:
            geojson["features"].append({
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "LineString", "coordinates": all_coords[0]}
            })
        elif len(all_coords) > 1:
            geojson["features"].append({
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "MultiLineString", "coordinates": all_coords}
            })

    # Routes -> LineStrings
    for rte in find_all_elem(root, 'rte'):
        properties = {}
        name_elem = find_elem(rte, 'name')
        if name_elem is not None and name_elem.text:
            properties['name'] = name_elem.text

        coords = []
        for rtept in rte.findall('gpx:rtept', ns) or rte.findall('rtept'):
            lat = float(rtept.get('lat'))
            lon = float(rtept.get('lon'))
            coords.append([lon, lat])

        if coords:
            geojson["features"].append({
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "LineString", "coordinates": coords}
            })

    return geojson


def read_csv(path: Union[str, Path], lat_col: str = 'lat', lon_col: str = 'lon') -> dict:
    """
    Read a CSV file with coordinate columns and convert to GeoJSON points.

    Args:
        path: Path to .csv file
        lat_col: Name of latitude column (case-insensitive)
        lon_col: Name of longitude column (case-insensitive)

    Returns:
        GeoJSON FeatureCollection dict
    """
    geojson = {"type": "FeatureCollection", "features": []}

    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        # Find lat/lon columns (case-insensitive)
        fieldnames_lower = {name.lower(): name for name in reader.fieldnames or []}
        lat_key = fieldnames_lower.get(lat_col.lower())
        lon_key = fieldnames_lower.get(lon_col.lower())

        # Try common alternatives
        if not lat_key:
            for alt in ['latitude', 'lat', 'y']:
                if alt in fieldnames_lower:
                    lat_key = fieldnames_lower[alt]
                    break
        if not lon_key:
            for alt in ['longitude', 'lon', 'lng', 'long', 'x']:
                if alt in fieldnames_lower:
                    lon_key = fieldnames_lower[alt]
                    break

        if not lat_key or not lon_key:
            raise ValueError(f"Could not find lat/lon columns. Available: {reader.fieldnames}")

        for row in reader:
            try:
                lat = float(row[lat_key])
                lon = float(row[lon_key])
            except (ValueError, TypeError):
                continue

            properties = {k: v for k, v in row.items() if k not in [lat_key, lon_key]}

            geojson["features"].append({
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "Point", "coordinates": [lon, lat]}
            })

    return geojson


def read_topojson(path: Union[str, Path]) -> dict:
    """
    Read a TopoJSON file and convert to GeoJSON.

    Args:
        path: Path to .topojson file

    Returns:
        GeoJSON FeatureCollection dict
    """
    with open(path, 'r', encoding='utf-8') as f:
        topo = json.load(f)

    geojson = {"type": "FeatureCollection", "features": []}

    # Get the transform if present
    transform = topo.get('transform')
    arcs = topo.get('arcs', [])

    def decode_arc(arc_index: int) -> list:
        """Decode an arc index to coordinates."""
        if arc_index < 0:
            coords = arcs[~arc_index][:]
            coords.reverse()
        else:
            coords = arcs[arc_index][:]

        if transform:
            scale = transform.get('scale', [1, 1])
            translate = transform.get('translate', [0, 0])
            decoded = []
            x, y = 0, 0
            for coord in coords:
                x += coord[0]
                y += coord[1]
                decoded.append([x * scale[0] + translate[0], y * scale[1] + translate[1]])
            return decoded
        return coords

    def arcs_to_coords(arc_indices: list) -> list:
        """Convert arc indices to coordinate ring."""
        coords = []
        for idx in arc_indices:
            arc_coords = decode_arc(idx)
            if coords:
                coords.extend(arc_coords[1:])
            else:
                coords.extend(arc_coords)
        return coords

    def geometry_to_geojson(geom: dict) -> Optional[dict]:
        """Convert TopoJSON geometry to GeoJSON geometry."""
        geom_type = geom.get('type')

        if geom_type == 'Point':
            coords = geom.get('coordinates', [])
            if transform:
                scale = transform.get('scale', [1, 1])
                translate = transform.get('translate', [0, 0])
                coords = [coords[0] * scale[0] + translate[0], coords[1] * scale[1] + translate[1]]
            return {"type": "Point", "coordinates": coords}

        elif geom_type == 'MultiPoint':
            coords = geom.get('coordinates', [])
            if transform:
                scale = transform.get('scale', [1, 1])
                translate = transform.get('translate', [0, 0])
                coords = [[c[0] * scale[0] + translate[0], c[1] * scale[1] + translate[1]] for c in coords]
            return {"type": "MultiPoint", "coordinates": coords}

        elif geom_type == 'LineString':
            arc_indices = geom.get('arcs', [])
            coords = arcs_to_coords(arc_indices)
            return {"type": "LineString", "coordinates": coords}

        elif geom_type == 'MultiLineString':
            lines = []
            for arc_indices in geom.get('arcs', []):
                lines.append(arcs_to_coords(arc_indices))
            return {"type": "MultiLineString", "coordinates": lines}

        elif geom_type == 'Polygon':
            rings = []
            for arc_indices in geom.get('arcs', []):
                rings.append(arcs_to_coords(arc_indices))
            return {"type": "Polygon", "coordinates": rings}

        elif geom_type == 'MultiPolygon':
            polygons = []
            for polygon_arcs in geom.get('arcs', []):
                rings = []
                for arc_indices in polygon_arcs:
                    rings.append(arcs_to_coords(arc_indices))
                polygons.append(rings)
            return {"type": "MultiPolygon", "coordinates": polygons}

        elif geom_type == 'GeometryCollection':
            return {
                "type": "GeometryCollection",
                "geometries": [geometry_to_geojson(g) for g in geom.get('geometries', [])]
            }

        return None

    # Process all objects
    for obj_name, obj in topo.get('objects', {}).items():
        if obj.get('type') == 'GeometryCollection':
            for geom in obj.get('geometries', []):
                properties = geom.get('properties', {})
                gj_geom = geometry_to_geojson(geom)
                if gj_geom:
                    geojson["features"].append({
                        "type": "Feature",
                        "properties": properties,
                        "geometry": gj_geom
                    })
        else:
            properties = obj.get('properties', {})
            gj_geom = geometry_to_geojson(obj)
            if gj_geom:
                geojson["features"].append({
                    "type": "Feature",
                    "properties": properties,
                    "geometry": gj_geom
                })

    return geojson


# Registry of readers by file extension
READERS = {
    '.shp': read_shapefile,
    '.geojson': read_geojson,
    '.json': read_geojson,
    '.kml': read_kml,
    '.kmz': read_kmz,
    '.gpx': read_gpx,
    '.csv': read_csv,
    '.topojson': read_topojson,
}
