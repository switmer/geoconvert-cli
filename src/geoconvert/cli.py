"""
Command-line interface for geoconvert.
"""

import argparse
import sys
from pathlib import Path

from .core import convert, probe, print_probe_report, convert_batch, collect_input_files
from .readers import READERS
from .writers import WRITERS


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="geoconvert",
        description="Universal Geospatial Format Converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Supported formats:
  Input:  {', '.join(sorted(READERS.keys()))}
  Output: {', '.join(sorted(WRITERS.keys()))}

Examples:
  # Single file conversion
  %(prog)s input.shp output.geojson
  %(prog)s input.geojson output.kml

  # Batch conversion
  %(prog)s input_dir/ output_dir/ --to kml
  %(prog)s input_dir/ output_dir/ --to geojson --recursive
  %(prog)s *.shp output_dir/ --to kml

  # With CRS handling
  %(prog)s utm_data.shp output.kml --src-crs EPSG:26915
  %(prog)s input_dir/ output_dir/ --to kml --assume-wgs84

  # Probe mode
  %(prog)s --probe input.shp
"""
    )

    # Mode flags
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Analyze file and report contents without converting"
    )
    parser.add_argument(
        "--to",
        metavar="EXT",
        help="Target format for batch conversion (e.g., kml, geojson)"
    )

    # Positional arguments - use remainder to handle flexible input/output
    parser.add_argument(
        "paths",
        nargs="+",
        help="Input file(s)/directory and output file/directory"
    )

    # Batch options
    batch_group = parser.add_argument_group("Batch options")
    batch_group.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Process subdirectories recursively"
    )
    batch_group.add_argument(
        "--pattern",
        metavar="GLOB",
        help="File pattern to match (e.g., '*.shp')"
    )
    batch_group.add_argument(
        "--include-ext",
        metavar="EXT",
        help="Comma-separated extensions to include (e.g., '.shp,.kml')"
    )
    batch_group.add_argument(
        "--exclude",
        metavar="GLOB",
        action="append",
        help="Glob pattern to exclude (can be repeated)"
    )
    batch_group.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files"
    )
    batch_group.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop batch processing on first error"
    )
    batch_group.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-file output"
    )
    batch_group.add_argument(
        "--summary",
        action="store_true",
        help="Print summary at end of batch"
    )
    batch_group.add_argument(
        "--report",
        metavar="FILE",
        help="Save batch report as JSON"
    )

    # CRS options
    crs_group = parser.add_argument_group("CRS options")
    crs_group.add_argument(
        "--src-crs",
        metavar="CRS",
        help="Source CRS (e.g., EPSG:26915). Overrides auto-detection from .prj"
    )
    crs_group.add_argument(
        "--force-src-crs",
        action="store_true",
        help="Force --src-crs even when file has detected CRS (batch mode)"
    )
    crs_group.add_argument(
        "--dst-crs",
        metavar="CRS",
        help="Destination CRS. Defaults to EPSG:4326 for KML output"
    )
    crs_group.add_argument(
        "--assume-wgs84",
        action="store_true",
        help="Assume input is WGS84 even without .prj file"
    )
    crs_group.add_argument(
        "--no-reproject",
        action="store_true",
        help="Skip reprojection entirely (advanced)"
    )

    # CSV input options
    csv_group = parser.add_argument_group("CSV options")
    csv_group.add_argument(
        "--lat",
        default="lat",
        help="Latitude column name for CSV input (default: lat)"
    )
    csv_group.add_argument(
        "--lon",
        default="lon",
        help="Longitude column name for CSV input (default: lon)"
    )

    # KML output options
    kml_group = parser.add_argument_group("KML options")
    kml_group.add_argument(
        "--name-field",
        default="name",
        help="Property field to use for KML placemark names (default: name)"
    )

    # CSV output options
    parser.add_argument(
        "--include-wkt",
        action="store_true",
        help="Include WKT geometry column in CSV output"
    )

    # SVG output options
    svg_group = parser.add_argument_group("SVG options")
    svg_group.add_argument(
        "--width",
        type=int,
        default=800,
        help="SVG width in pixels (default: 800)"
    )
    svg_group.add_argument(
        "--height",
        type=int,
        default=600,
        help="SVG height in pixels (default: 600)"
    )

    # Version
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0"
    )

    args = parser.parse_args()

    # Parse paths: determine input(s) and output based on mode
    paths = [Path(p) for p in args.paths]

    # =========================================================================
    # PROBE MODE - all paths are inputs
    # =========================================================================
    if args.probe:
        for input_path in paths:
            if input_path.exists():
                result = probe(input_path)
                print_probe_report(result)
            else:
                print(f"Error: Input not found: {input_path}")
        sys.exit(0)

    # =========================================================================
    # BATCH MODE (--to flag present)
    # Last path is output directory, rest are inputs
    # =========================================================================
    if args.to:
        if len(paths) < 2:
            print("Error: Batch mode requires input and output directory")
            print("  Usage: geoconvert input_dir/ output_dir/ --to kml")
            sys.exit(1)

        # Last path is output directory
        output_dir = paths[-1]
        input_paths = paths[:-1]

        # Validate input paths exist
        for p in input_paths:
            if not p.exists():
                print(f"Error: Input not found: {p}")
                sys.exit(1)

        # Collect input files
        all_files = []
        input_base_dir = None

        for input_path in input_paths:
            if input_path.is_dir():
                input_base_dir = input_path
                include_ext = args.include_ext.split(',') if args.include_ext else None
                files = collect_input_files(
                    input_path,
                    recursive=args.recursive,
                    pattern=args.pattern,
                    include_ext=include_ext,
                    exclude=args.exclude,
                )
                all_files.extend(files)
            elif input_path.exists():
                all_files.append(input_path)

        if not all_files:
            print("Error: No input files found")
            sys.exit(1)

        print(f"Found {len(all_files)} files to convert")

        # Run batch conversion
        result = convert_batch(
            all_files,
            output_dir,
            args.to,
            recursive=args.recursive,
            input_base_dir=input_base_dir,
            overwrite=args.overwrite,
            continue_on_error=not args.stop_on_error,
            quiet=args.quiet,
            src_crs=args.src_crs,
            force_src_crs=args.force_src_crs,
            dst_crs=args.dst_crs,
            assume_wgs84=args.assume_wgs84,
            no_reproject=args.no_reproject,
            lat=args.lat,
            lon=args.lon,
            name_field=args.name_field,
            include_wkt=args.include_wkt,
            width=args.width,
            height=args.height,
        )

        # Print summary if requested or if there were failures
        if args.summary or result.failed > 0:
            result.print_summary()

        # Save report if requested
        if args.report:
            result.save_report(args.report)
            print(f"Report saved to: {args.report}")

        sys.exit(0 if result.failed == 0 else 1)

    # =========================================================================
    # SINGLE FILE MODE
    # Exactly 2 paths: input and output
    # =========================================================================
    if len(paths) < 2:
        print("Error: Output file path required for conversion")
        print("  Usage: geoconvert input.shp output.geojson")
        print("  Use --probe for file analysis without conversion")
        print("  Use --to for batch conversion")
        sys.exit(1)

    if len(paths) > 2:
        print("Error: Single file mode requires exactly one input and one output")
        print("  For multiple files, use: geoconvert input_dir/ output_dir/ --to FORMAT")
        sys.exit(1)

    input_path = paths[0]
    output_path = paths[1]

    if not input_path.exists():
        print(f"Error: Input not found: {input_path}")
        sys.exit(1)

    success = convert(
        input_path,
        output_path,
        src_crs=args.src_crs,
        dst_crs=args.dst_crs,
        assume_wgs84=args.assume_wgs84,
        no_reproject=args.no_reproject,
        lat=args.lat,
        lon=args.lon,
        name_field=args.name_field,
        include_wkt=args.include_wkt,
        width=args.width,
        height=args.height,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
