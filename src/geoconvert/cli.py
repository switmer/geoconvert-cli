"""
Command-line interface for geoconvert.

Provides a Unix-style CLI with subcommands:
  - convert: Convert a single file
  - probe: Analyze file(s) and report contents
  - batch: Convert multiple files
  - formats: List supported formats
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

from .core import (
    convert,
    probe,
    print_probe_report,
    convert_batch,
    collect_input_files,
    ConvertResult,
    EXIT_SUCCESS,
    EXIT_ERROR,
    EXIT_PARTIAL,
)
from .readers import READERS
from .writers import WRITERS

__version__ = "0.2.0"

# Known subcommands for legacy detection
SUBCOMMANDS = {"convert", "probe", "batch", "formats"}


# ============================================================================
# ARGUMENT PARSER
# ============================================================================

def _add_crs_args(parser: argparse.ArgumentParser):
    """Add CRS-related arguments to a parser."""
    crs_group = parser.add_argument_group("CRS options")
    crs_group.add_argument(
        "--src-crs",
        metavar="CRS",
        help="Source CRS (e.g., EPSG:26915). Overrides auto-detection from .prj"
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


def _add_format_args(parser: argparse.ArgumentParser):
    """Add format-specific arguments to a parser."""
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
    csv_group.add_argument(
        "--include-wkt",
        action="store_true",
        help="Include WKT geometry column in CSV output"
    )

    # KML output options
    kml_group = parser.add_argument_group("KML options")
    kml_group.add_argument(
        "--name-field",
        default="name",
        help="Property field to use for KML placemark names (default: name)"
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


def _add_batch_args(parser: argparse.ArgumentParser):
    """Add batch-specific arguments to a parser."""
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
        "--summary",
        action="store_true",
        help="Print summary at end of batch"
    )
    batch_group.add_argument(
        "--report",
        metavar="FILE",
        help="Save batch report as JSON"
    )
    batch_group.add_argument(
        "--force-src-crs",
        action="store_true",
        help="Force --src-crs even when file has detected CRS"
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with subcommands."""
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
  geoconvert convert input.shp output.geojson
  geoconvert convert input.geojson output.kml --assume-wgs84

  # Batch conversion
  geoconvert batch input_dir/ output_dir/ --to kml
  geoconvert batch input_dir/ output_dir/ --to geojson --recursive --json

  # Probe files
  geoconvert probe input.shp
  geoconvert probe *.shp --json

  # List formats
  geoconvert formats --json

  # Streaming (text formats only)
  cat data.geojson | geoconvert convert - output.kml --from geojson
  geoconvert convert input.shp - --to geojson | jq '.features | length'
"""
    )

    # Global options
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress informational output"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Create parent parser for common options
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parent_parser.add_argument("--quiet", "-q", action="store_true", help="Suppress informational output")

    # -------------------------------------------------------------------------
    # geoconvert convert input output
    # -------------------------------------------------------------------------
    convert_parser = subparsers.add_parser(
        "convert",
        parents=[parent_parser],
        help="Convert a single file",
        description="Convert a single geospatial file to another format."
    )
    convert_parser.add_argument("input", help="Input file path (use '-' for stdin)")
    convert_parser.add_argument("output", help="Output file path (use '-' for stdout)")
    convert_parser.add_argument(
        "--from",
        dest="from_format",
        metavar="EXT",
        help="Input format when reading from stdin (e.g., geojson)"
    )
    convert_parser.add_argument(
        "--to",
        dest="to_format",
        metavar="EXT",
        help="Output format when writing to stdout (e.g., kml)"
    )
    _add_crs_args(convert_parser)
    _add_format_args(convert_parser)

    # -------------------------------------------------------------------------
    # geoconvert probe file [file ...]
    # -------------------------------------------------------------------------
    probe_parser = subparsers.add_parser(
        "probe",
        parents=[parent_parser],
        help="Analyze file(s) and report contents",
        description="Analyze geospatial files and report their contents without converting."
    )
    probe_parser.add_argument("files", nargs="+", help="File(s) to analyze")

    # -------------------------------------------------------------------------
    # geoconvert batch input_dir output_dir --to EXT
    # -------------------------------------------------------------------------
    batch_parser = subparsers.add_parser(
        "batch",
        parents=[parent_parser],
        help="Convert multiple files",
        description="Convert multiple geospatial files to a target format."
    )
    batch_parser.add_argument("input_dir", help="Input directory or files")
    batch_parser.add_argument("output_dir", help="Output directory")
    batch_parser.add_argument(
        "--to",
        required=True,
        metavar="EXT",
        help="Target format (e.g., kml, geojson)"
    )
    _add_batch_args(batch_parser)
    _add_crs_args(batch_parser)
    _add_format_args(batch_parser)

    # -------------------------------------------------------------------------
    # geoconvert formats
    # -------------------------------------------------------------------------
    subparsers.add_parser(
        "formats",
        parents=[parent_parser],
        help="List supported formats",
        description="List all supported input and output formats."
    )

    return parser


# ============================================================================
# LEGACY ARGUMENT REWRITING
# ============================================================================

def _rewrite_legacy_probe(argv: List[str]) -> List[str]:
    """
    Rewrite legacy --probe syntax to new subcommand syntax.

    geoconvert --probe file.shp -> geoconvert probe file.shp
    """
    new_argv = [argv[0], "probe"]
    for arg in argv[1:]:
        if arg != "--probe":
            new_argv.append(arg)
    return new_argv


def _rewrite_legacy_batch(argv: List[str]) -> List[str]:
    """
    Rewrite legacy batch syntax to new subcommand syntax.

    geoconvert dir/ out/ --to kml -> geoconvert batch dir/ out/ --to kml
    """
    new_argv = [argv[0], "batch"]
    new_argv.extend(argv[1:])
    return new_argv


def _rewrite_legacy_single(argv: List[str]) -> List[str]:
    """
    Rewrite legacy single-file syntax to new subcommand syntax.

    geoconvert input.shp output.kml -> geoconvert convert input.shp output.kml
    """
    return [argv[0], "convert"] + argv[1:]


def _detect_and_rewrite_legacy(argv: List[str]) -> List[str]:
    """
    Detect legacy invocation patterns and rewrite to new subcommand syntax.

    Returns rewritten argv if legacy pattern detected, otherwise original.
    """
    if len(argv) <= 1:
        return argv

    # If first positional arg is already a subcommand, no rewriting needed
    if argv[1] in SUBCOMMANDS:
        return argv

    # Check for --version, --help which don't need rewriting
    if argv[1] in ("--version", "-v", "--help", "-h"):
        return argv

    # Check for --probe flag anywhere
    if "--probe" in argv:
        return _rewrite_legacy_probe(argv)

    # Check for --to flag (indicates batch mode in legacy)
    if "--to" in argv:
        return _rewrite_legacy_batch(argv)

    # Check for two positional arguments (legacy single file mode)
    # Count non-flag arguments
    positionals = [a for a in argv[1:] if not a.startswith("-")]
    if len(positionals) >= 2:
        # Looks like: geoconvert input.shp output.kml [options]
        return _rewrite_legacy_single(argv)

    return argv


# ============================================================================
# SUBCOMMAND HANDLERS
# ============================================================================

def cmd_convert(args) -> int:
    """Handle the 'convert' subcommand."""
    input_path = args.input
    output_path = args.output

    # Handle stdin/stdout
    is_stdin = (input_path == "-")
    is_stdout = (output_path == "-")

    # Validate stdin requirements
    if is_stdin and not args.from_format:
        print("Error: --from EXT is required when reading from stdin", file=sys.stderr)
        return EXIT_ERROR

    # Validate stdout requirements
    if is_stdout and not args.to_format:
        print("Error: --to EXT is required when writing to stdout", file=sys.stderr)
        return EXIT_ERROR

    # When writing to stdout or JSON mode, force quiet mode for clean output
    quiet = args.quiet or is_stdout or args.json

    result = convert(
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
        quiet=quiet,
        input_format=args.from_format,
        output_format=args.to_format,
    )

    if args.json:
        print(json.dumps(result.to_dict()))
    elif result.status == "error" and not args.quiet:
        print(f"Error: {result.error}", file=sys.stderr)

    return EXIT_SUCCESS if result.status == "success" else EXIT_ERROR


def cmd_probe(args) -> int:
    """Handle the 'probe' subcommand."""
    results = []

    for file_path in args.files:
        path = Path(file_path)
        if not path.exists():
            if args.json:
                results.append({"path": str(path), "error": "File not found"})
            else:
                print(f"Error: File not found: {path}", file=sys.stderr)
            continue

        result = probe(path)
        results.append(result)

        if not args.json:
            print_probe_report(result)

    if args.json:
        # Output each result as a line of JSON (NDJSON for multiple files)
        if len(results) == 1:
            print(json.dumps(results[0], default=list))
        else:
            for r in results:
                print(json.dumps(r, default=list))

    return EXIT_SUCCESS


def cmd_batch(args) -> int:
    """Handle the 'batch' subcommand."""
    input_path = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    # Validate input exists
    if not input_path.exists():
        print(f"Error: Input not found: {input_path}", file=sys.stderr)
        return EXIT_ERROR

    # Collect input files
    include_ext = args.include_ext.split(',') if args.include_ext else None
    files = collect_input_files(
        input_path,
        recursive=args.recursive,
        pattern=args.pattern,
        include_ext=include_ext,
        exclude=args.exclude,
    )

    if not files:
        print("Error: No input files found", file=sys.stderr)
        return EXIT_ERROR

    if not args.quiet and not args.json:
        print(f"Found {len(files)} files to convert", file=sys.stderr)

    # Run batch conversion
    result = convert_batch(
        files,
        output_dir,
        args.to,
        recursive=args.recursive,
        input_base_dir=input_path if input_path.is_dir() else None,
        overwrite=args.overwrite,
        continue_on_error=not args.stop_on_error,
        quiet=args.quiet or args.json,
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

    if args.json:
        # NDJSON output: one line per file, then summary
        for file_result in result.files:
            print(json.dumps(file_result.to_dict()))
        print(json.dumps({
            "summary": {
                "total": result.total,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "skipped": result.skipped,
            }
        }))
    else:
        # Print summary if requested or if there were failures
        if args.summary or result.failed > 0:
            result.print_summary()

    # Save report if requested
    if args.report:
        result.save_report(args.report)
        if not args.quiet:
            print(f"Report saved to: {args.report}", file=sys.stderr)

    # Determine exit code
    if result.failed == 0:
        return EXIT_SUCCESS
    elif result.succeeded > 0:
        return EXIT_PARTIAL
    else:
        return EXIT_ERROR


def cmd_formats(args) -> int:
    """Handle the 'formats' subcommand."""
    # Define streamable formats
    text_formats = {'.geojson', '.json', '.kml', '.gpx', '.csv', '.wkt', '.topojson'}

    if args.json:
        output = {
            "input": [
                {"format": ext, "streamable": ext in text_formats}
                for ext in sorted(READERS.keys())
            ],
            "output": [
                {"format": ext, "streamable": ext in text_formats}
                for ext in sorted(WRITERS.keys())
            ]
        }
        print(json.dumps(output, indent=2))
    else:
        print("Supported formats:")
        print(f"  Input:  {', '.join(sorted(READERS.keys()))}")
        print(f"  Output: {', '.join(sorted(WRITERS.keys()))}")
        print(f"\nStreamable (stdin/stdout): {', '.join(sorted(text_formats))}")

    return EXIT_SUCCESS


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point for the CLI."""
    # Rewrite legacy invocations to new subcommand syntax
    sys.argv = _detect_and_rewrite_legacy(sys.argv)

    parser = create_parser()
    args = parser.parse_args()

    # Handle no command
    if not args.command:
        parser.print_help()
        sys.exit(EXIT_ERROR)

    # Dispatch to subcommand handler
    handlers = {
        "convert": cmd_convert,
        "probe": cmd_probe,
        "batch": cmd_batch,
        "formats": cmd_formats,
    }

    handler = handlers.get(args.command)
    if handler:
        exit_code = handler(args)
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(EXIT_ERROR)


if __name__ == "__main__":
    main()
