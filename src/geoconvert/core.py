"""
Core conversion functions with CRS handling.
"""

import fnmatch
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Union, List, Dict, Any

from .readers import READERS
from .writers import WRITERS
from .crs import (
    WGS84,
    normalize_crs,
    get_crs_name,
    create_transformer,
    transform_geojson,
    requires_wgs84,
    detect_crs_from_geojson,
)


def get_supported_formats() -> dict:
    """
    Get supported input and output formats.

    Returns:
        Dict with 'input' and 'output' keys listing supported extensions
    """
    return {
        "input": list(READERS.keys()),
        "output": list(WRITERS.keys()),
    }


def convert(
    input_path: Union[str, Path],
    output_path: Union[str, Path],
    *,
    src_crs: Optional[str] = None,
    dst_crs: Optional[str] = None,
    assume_wgs84: bool = False,
    no_reproject: bool = False,
    lat: str = 'lat',
    lon: str = 'lon',
    name_field: str = 'name',
    include_wkt: bool = False,
    width: int = 800,
    height: int = 600,
) -> bool:
    """
    Convert between geospatial formats with optional reprojection.

    Args:
        input_path: Input file path
        output_path: Output file path
        src_crs: Source CRS (e.g., "EPSG:26915"). Overrides auto-detection.
        dst_crs: Destination CRS. Defaults to EPSG:4326 for KML output.
        assume_wgs84: Assume input is WGS84 even without .prj file
        no_reproject: Skip reprojection entirely (advanced escape hatch)
        lat: Latitude column name (for CSV input)
        lon: Longitude column name (for CSV input)
        name_field: Property field for KML placemark names
        include_wkt: Include WKT geometry in CSV output
        width: SVG width in pixels
        height: SVG height in pixels

    Returns:
        True if conversion succeeded, False otherwise

    Example:
        >>> convert("input.shp", "output.geojson")
        >>> convert("utm_data.shp", "map.kml", src_crs="EPSG:26915")
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    input_ext = input_path.suffix.lower()
    output_ext = output_path.suffix.lower()

    # Get reader
    reader = READERS.get(input_ext)
    if not reader:
        print(f"Error: Unsupported input format: {input_ext}")
        print(f"Supported: {', '.join(READERS.keys())}")
        return False

    # Get writer
    writer = WRITERS.get(output_ext)
    if not writer:
        print(f"Error: Unsupported output format: {output_ext}")
        print(f"Supported: {', '.join(WRITERS.keys())}")
        return False

    print(f"Converting {input_path.name} -> {output_path.name}")

    # Read input (special handling for CSV)
    if input_ext == '.csv':
        from .readers import read_csv
        geojson = read_csv(input_path, lat_col=lat, lon_col=lon)
        # CSV with lat/lon is assumed WGS84
        if not src_crs:
            src_crs = WGS84
    else:
        geojson = reader(input_path)

    # Determine source CRS
    detected_crs = None
    if not src_crs:
        # Check if reader detected CRS (e.g., from .prj)
        detected_crs = geojson.pop("_crs", None)

        # Check deprecated GeoJSON crs field
        if not detected_crs:
            detected_crs = detect_crs_from_geojson(geojson)

        if detected_crs:
            src_crs = detected_crs
            print(f"  Detected CRS: {get_crs_name(normalize_crs(src_crs))}")
        elif assume_wgs84:
            src_crs = WGS84
            print("  Assuming WGS84 (--assume-wgs84)")
        elif requires_wgs84(output_ext):
            print(f"Error: Output format {output_ext} requires WGS84, but no CRS detected.")
            print("  Options:")
            print("    --src-crs EPSG:XXXX  (specify the source CRS)")
            print("    --assume-wgs84       (if you know it's already WGS84)")
            return False

    # Determine destination CRS
    if not dst_crs:
        if requires_wgs84(output_ext):
            dst_crs = WGS84
        elif src_crs:
            # Preserve source CRS for other formats
            dst_crs = src_crs
        else:
            dst_crs = WGS84  # Default fallback

    # Perform reprojection if needed
    if src_crs and dst_crs and not no_reproject:
        src_crs_obj = normalize_crs(src_crs)
        dst_crs_obj = normalize_crs(dst_crs)

        if src_crs_obj and dst_crs_obj:
            transformer = create_transformer(src_crs_obj, dst_crs_obj)
            if transformer:
                print(f"  Reprojecting: {get_crs_name(src_crs_obj)} -> {get_crs_name(dst_crs_obj)}")
                geojson = transform_geojson(geojson, transformer)

    # Write output with format-specific options
    if output_ext == '.kml':
        writer(geojson, output_path, name_field=name_field)
    elif output_ext == '.csv':
        writer(geojson, output_path, include_wkt=include_wkt)
    elif output_ext == '.svg':
        writer(geojson, output_path, width=width, height=height)
    else:
        writer(geojson, output_path)

    return True


# ============================================================================
# BATCH MODE
# ============================================================================

@dataclass
class FileResult:
    """Result of converting a single file in batch mode."""
    input_path: str
    output_path: str
    status: str  # "ok", "skipped", "failed"
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    feature_count: Optional[int] = None
    geometry_types: Optional[List[str]] = None
    detected_crs: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BatchResult:
    """Result of a batch conversion operation."""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    files: List[FileResult] = field(default_factory=list)

    def add(self, result: FileResult):
        self.files.append(result)
        self.total += 1
        if result.status == "ok":
            self.succeeded += 1
        elif result.status == "failed":
            self.failed += 1
        elif result.status == "skipped":
            self.skipped += 1

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "files": [f.to_dict() for f in self.files],
        }

    def save_report(self, path: Union[str, Path]):
        """Save batch report as JSON."""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)

    def print_summary(self):
        """Print summary to stdout."""
        print(f"\nBatch conversion complete:")
        print(f"  Total:     {self.total}")
        print(f"  Succeeded: {self.succeeded}")
        print(f"  Failed:    {self.failed}")
        print(f"  Skipped:   {self.skipped}")

        if self.failed > 0:
            print("\nFailed files:")
            for f in self.files:
                if f.status == "failed":
                    print(f"  {f.input_path}: {f.error}")


def collect_input_files(
    input_path: Path,
    recursive: bool = False,
    pattern: Optional[str] = None,
    include_ext: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> List[Path]:
    """
    Collect input files from a directory.

    Args:
        input_path: Directory to search
        recursive: Search subdirectories
        pattern: Glob pattern (e.g., "*.shp")
        include_ext: List of extensions to include (e.g., [".shp", ".kml"])
        exclude: List of glob patterns to exclude (e.g., ["*/cache/*"])

    Returns:
        List of input file paths
    """
    if not input_path.is_dir():
        return [input_path] if input_path.exists() else []

    # Determine which extensions to look for
    if include_ext:
        extensions = [ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in include_ext]
    else:
        extensions = list(READERS.keys())

    # Collect files
    files = []
    glob_pattern = "**/*" if recursive else "*"

    for ext in extensions:
        if pattern:
            # Use custom pattern
            search_pattern = pattern if recursive else pattern
            found = list(input_path.glob(f"**/{search_pattern}" if recursive else search_pattern))
        else:
            found = list(input_path.glob(f"{glob_pattern}{ext}"))

        files.extend(found)

    # Apply exclusions
    if exclude:
        filtered = []
        for f in files:
            excluded = False
            for exc_pattern in exclude:
                if fnmatch.fnmatch(str(f), exc_pattern):
                    excluded = True
                    break
            if not excluded:
                filtered.append(f)
        files = filtered

    # Remove duplicates and sort
    files = sorted(set(files))

    return files


def convert_batch(
    input_paths: List[Path],
    output_dir: Path,
    to_ext: str,
    *,
    recursive: bool = False,
    input_base_dir: Optional[Path] = None,
    overwrite: bool = False,
    continue_on_error: bool = True,
    quiet: bool = False,
    src_crs: Optional[str] = None,
    force_src_crs: bool = False,
    dst_crs: Optional[str] = None,
    assume_wgs84: bool = False,
    no_reproject: bool = False,
    lat: str = 'lat',
    lon: str = 'lon',
    name_field: str = 'name',
    include_wkt: bool = False,
    width: int = 800,
    height: int = 600,
) -> BatchResult:
    """
    Convert multiple files to a target format.

    Args:
        input_paths: List of input file paths
        output_dir: Output directory
        to_ext: Target extension (e.g., ".kml")
        recursive: Preserve directory structure from input
        input_base_dir: Base directory for computing relative paths
        overwrite: Overwrite existing output files
        continue_on_error: Continue processing after failures
        quiet: Suppress per-file output
        src_crs: Source CRS override
        force_src_crs: Force src_crs even when file has detected CRS
        dst_crs: Destination CRS
        assume_wgs84: Assume WGS84 when no CRS detected
        no_reproject: Skip reprojection
        lat: Latitude column for CSV
        lon: Longitude column for CSV
        name_field: Name field for KML
        include_wkt: Include WKT in CSV output
        width: SVG width
        height: SVG height

    Returns:
        BatchResult with per-file status
    """
    # Normalize output extension
    if not to_ext.startswith('.'):
        to_ext = f'.{to_ext}'
    to_ext = to_ext.lower()

    if to_ext not in WRITERS:
        raise ValueError(f"Unsupported output format: {to_ext}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = BatchResult()

    for input_path in input_paths:
        input_path = Path(input_path)

        # Compute output path
        if input_base_dir and recursive:
            # Preserve directory structure
            rel_path = input_path.relative_to(input_base_dir)
            output_path = output_dir / rel_path.with_suffix(to_ext)
            output_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # Flat output
            output_path = output_dir / input_path.with_suffix(to_ext).name

        # Check if output exists
        if output_path.exists() and not overwrite:
            file_result = FileResult(
                input_path=str(input_path),
                output_path=str(output_path),
                status="skipped",
                error="Output file exists (use --overwrite to replace)",
            )
            result.add(file_result)
            if not quiet:
                print(f"SKIP {input_path.name} (exists)")
            continue

        # Attempt conversion
        try:
            # Check if we need to warn about CRS override
            effective_src_crs = src_crs
            warnings = []

            if src_crs and not force_src_crs:
                # Probe to see if file has detected CRS
                probe_result = probe(input_path)
                detected = probe_result.get("crs")
                if detected and detected != "Unknown" and detected != src_crs:
                    warnings.append(f"Detected CRS {detected} overridden by --src-crs {src_crs}")

            # Suppress print output for batch mode
            import io
            import sys
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

            try:
                success = convert(
                    input_path,
                    output_path,
                    src_crs=effective_src_crs,
                    dst_crs=dst_crs,
                    assume_wgs84=assume_wgs84,
                    no_reproject=no_reproject,
                    lat=lat,
                    lon=lon,
                    name_field=name_field,
                    include_wkt=include_wkt,
                    width=width,
                    height=height,
                )
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            if success:
                # Get feature count from output if possible
                feature_count = None
                geometry_types = None
                try:
                    probe_out = probe(output_path)
                    feature_count = probe_out.get("feature_count")
                    geometry_types = probe_out.get("geometry_types")
                except Exception:
                    pass

                file_result = FileResult(
                    input_path=str(input_path),
                    output_path=str(output_path),
                    status="ok",
                    warnings=warnings,
                    feature_count=feature_count,
                    geometry_types=geometry_types,
                )
                if not quiet:
                    print(f"OK   {input_path.name} -> {output_path.name}")
            else:
                # Extract error from captured output
                error_msg = output.strip() if output else "Conversion failed"
                file_result = FileResult(
                    input_path=str(input_path),
                    output_path=str(output_path),
                    status="failed",
                    error=error_msg,
                    warnings=warnings,
                )
                if not quiet:
                    print(f"FAIL {input_path.name}: {error_msg}")

            result.add(file_result)

        except Exception as e:
            file_result = FileResult(
                input_path=str(input_path),
                output_path=str(output_path),
                status="failed",
                error=str(e),
            )
            result.add(file_result)
            if not quiet:
                print(f"FAIL {input_path.name}: {e}")

            if not continue_on_error:
                break

    return result


def probe(input_path: Union[str, Path]) -> dict:
    """
    Probe a file and report what it contains.

    Args:
        input_path: Path to the input file

    Returns:
        Dict with file information:
            - format: detected format
            - crs: detected CRS or "Unknown"
            - feature_count: number of features
            - geometry_types: set of geometry types present
            - properties: list of property names
            - warnings: list of potential issues
    """
    input_path = Path(input_path)
    input_ext = input_path.suffix.lower()

    result = {
        "path": str(input_path),
        "format": input_ext,
        "crs": "Unknown",
        "crs_is_geographic": None,
        "feature_count": 0,
        "geometry_types": set(),
        "properties": set(),
        "has_z": False,
        "warnings": [],
    }

    # Check if format is supported
    reader = READERS.get(input_ext)
    if not reader:
        result["warnings"].append(f"Unsupported format: {input_ext}")
        return result

    try:
        # Read the file
        geojson = reader(input_path)

        # Check for CRS
        detected_crs = geojson.pop("_crs", None)
        if not detected_crs:
            detected_crs = detect_crs_from_geojson(geojson)

        if detected_crs:
            crs_obj = normalize_crs(detected_crs)
            if crs_obj:
                result["crs"] = get_crs_name(crs_obj)
                result["crs_is_geographic"] = crs_obj.is_geographic
                if not crs_obj.is_geographic:
                    result["warnings"].append("CRS is projected (not lat/lon). KML output requires reprojection.")
        else:
            if input_ext == '.shp':
                # Check if .prj exists
                prj_path = input_path.with_suffix('.prj')
                if not prj_path.exists():
                    result["warnings"].append("No .prj file found. CRS unknown.")
            result["warnings"].append("CRS not detected. Use --src-crs or --assume-wgs84 for KML output.")

        # Analyze features
        features = geojson.get("features", [])
        result["feature_count"] = len(features)

        for feature in features:
            # Collect geometry types
            geom = feature.get("geometry", {})
            if geom:
                result["geometry_types"].add(geom.get("type"))

                # Check for Z coordinates
                coords = geom.get("coordinates", [])
                if _has_z_coords(coords):
                    result["has_z"] = True

            # Collect property names
            props = feature.get("properties", {})
            result["properties"].update(props.keys())

        # Convert sets to sorted lists for serialization
        result["geometry_types"] = sorted(result["geometry_types"])
        result["properties"] = sorted(result["properties"])

        # Format-specific checks
        if input_ext == '.kml':
            _probe_kml_extras(input_path, result)

    except Exception as e:
        result["warnings"].append(f"Error reading file: {e}")

    return result


def _has_z_coords(coords) -> bool:
    """Recursively check if coordinates have Z values."""
    if not coords:
        return False
    if isinstance(coords[0], (int, float)):
        return len(coords) > 2
    return any(_has_z_coords(c) for c in coords)


def _probe_kml_extras(path: Path, result: dict):
    """Check for KML features that will be dropped."""
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(path)
        root = tree.getroot()

        # Handle namespace
        ns = ""
        if root.tag.startswith('{'):
            ns = root.tag.split('}')[0] + '}'

        # Check for elements that will be ignored
        dropped = []

        if root.findall(f'.//{ns}NetworkLink'):
            dropped.append("NetworkLink (remote data)")
        if root.findall(f'.//{ns}GroundOverlay'):
            dropped.append("GroundOverlay (images)")
        if root.findall(f'.//{ns}ScreenOverlay'):
            dropped.append("ScreenOverlay")
        if root.findall(f'.//{ns}Style') or root.findall(f'.//{ns}StyleMap'):
            dropped.append("Styles (colors, icons)")
        if root.findall(f'.//{ns}TimeSpan') or root.findall(f'.//{ns}TimeStamp'):
            dropped.append("Temporal data")

        folders = root.findall(f'.//{ns}Folder')
        if folders:
            result["warnings"].append(f"Contains {len(folders)} folders (will be flattened)")

        if dropped:
            result["warnings"].append(f"Will drop: {', '.join(dropped)}")

    except Exception:
        pass


def print_probe_report(result: dict):
    """Print a formatted probe report."""
    print(f"\nFile: {result['path']}")
    print(f"Format: {result['format']}")
    print(f"CRS: {result['crs']}")
    if result['crs_is_geographic'] is not None:
        print(f"  Geographic (lat/lon): {'Yes' if result['crs_is_geographic'] else 'No (projected)'}")
    print(f"Features: {result['feature_count']}")

    if result['geometry_types']:
        print(f"Geometry types: {', '.join(result['geometry_types'])}")

    if result['has_z']:
        print("Has Z coordinates: Yes")

    if result['properties']:
        print(f"Properties: {', '.join(result['properties'][:10])}", end="")
        if len(result['properties']) > 10:
            print(f" ... and {len(result['properties']) - 10} more")
        else:
            print()

    if result['warnings']:
        print("\nWarnings:")
        for w in result['warnings']:
            print(f"  - {w}")
