from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .api import (
    InterfaceMatchRequest,
    ToolUnavailableError,
    VaspkitExtractionRequest,
    VolumeSliceRequest,
    analyze_interface,
    configure_external_tool,
    extract_vaspkit_volumes,
    marker_from_match,
    render_volume_slice,
    run_hstructpy,
    tool_status,
)
from .core import (audit_runs, collect_archive, hydrate_scaffold, ingest, plot, propose,
                   scaffold_direct_static, scaffold_relax, scaffold_static, submit_runs,
                   validate_scaffold, write_json)


PACKAGE_ROOT = Path(__file__).resolve().parent
CLI_REFERENCE = PACKAGE_ROOT / "data" / "CLI_REFERENCE.md"
DEFAULT_CONFIG = {
    "schema": "epirefine.config.v1", "system": "RuO2", "planes": ["001", "100", "110"],
    "strain_bounds_percent": [-10.0, 10.0], "budget": 50, "low_moment": 0.05,
    "high_moment": 0.15, "min_response_span": 0.18,
    "max_unresolved_diameter_percent": 0.55, "min_triangle_quality": 0.01,
    "boundary_spacing_percent": 0.45, "pocket_spacing_percent": 0.12,
    "barycentric_divisions": 18, "moment_species": ["Ru"], "seed": 20260928,
    "relax_vasp_command": "vasp_std", "static_vasp_command": "vasp_std"
}


def config(path: Path | None) -> dict:
    result = dict(DEFAULT_CONFIG)
    if path:
        result.update(json.loads(path.read_text()))
    return result


def template_root(path: Path | None) -> Path:
    """Use project-owned editable templates when config.json is supplied."""
    if path and (path.resolve().parent / "templates").is_dir():
        return path.resolve().parent
    return PACKAGE_ROOT


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="epirefine",
        description="Heterostructure analysis and adaptive epitaxial-strain HPC workflow",
        epilog=("Run 'epirefine help-all' for the complete reference and three examples per command. "
                "Run 'epirefine-tui' for the optional guided terminal interface."),
    )
    top.add_argument("--version", action="version", version=__version__)
    sub = top.add_subparsers(dest="command", required=True)
    command = sub.add_parser("init", help="create a project and editable config/templates")
    command.add_argument("project", type=Path)
    command.add_argument("--system")
    command.add_argument("--ensure-layout", action="store_true",
                         help="add only missing standard directories/files to an existing project")
    command = sub.add_parser("propose", help="make Delaunay/gradient/zero-pocket proposals")
    command.add_argument("--input", type=Path, required=True); command.add_argument("--out", type=Path, required=True)
    command.add_argument("--config", type=Path); command.add_argument("--budget", type=int); command.add_argument("--iteration", default="next")
    command = sub.add_parser("scaffold-relax", help="strain nearest accepted CONTCARs into relaxation inputs")
    command.add_argument("--points", type=Path, required=True); command.add_argument("--history", type=Path, required=True)
    command.add_argument("--source-root", type=Path, required=True); command.add_argument("--out", type=Path, required=True)
    command.add_argument("--config", type=Path); command.add_argument("--potcar", type=Path); command.add_argument("--kpoints", type=Path)
    command.add_argument("--dry-run", action="store_true")
    command = sub.add_parser("scaffold-direct-static",
                             help="strain nearest accepted geometries directly into static inputs")
    command.add_argument("--points", type=Path, required=True); command.add_argument("--history", type=Path, required=True)
    command.add_argument("--source-root", type=Path, required=True); command.add_argument("--out", type=Path, required=True)
    command.add_argument("--config", type=Path); command.add_argument("--potcar", type=Path); command.add_argument("--kpoints", type=Path)
    command.add_argument("--dry-run", action="store_true")
    command = sub.add_parser("scaffold-static", help="audit relaxations and create static inputs")
    command.add_argument("--relax-manifest", type=Path, required=True); command.add_argument("--relax-results", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True); command.add_argument("--config", type=Path)
    command.add_argument("--potcar", type=Path); command.add_argument("--kpoints", type=Path); command.add_argument("--dry-run", action="store_true")
    command = sub.add_parser("ingest", help="reduce static OUTCARs using their manifest")
    command.add_argument("--results", type=Path, required=True); command.add_argument("--manifest", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True); command.add_argument("--history", type=Path); command.add_argument("--config", type=Path)
    command = sub.add_parser("plot", help="make side-by-side contours and sampling history")
    command.add_argument("--input", type=Path, required=True); command.add_argument("--out", type=Path, required=True)
    command.add_argument("--planes", nargs="+"); command.add_argument("--markers", type=Path)
    command = sub.add_parser("validate", help="verify a relax/static scaffold and its input hashes")
    command.add_argument("--manifest", type=Path, required=True); command.add_argument("--root", type=Path)
    command = sub.add_parser("hydrate", help="add licensed/site-specific POTCAR or KPOINTS inputs")
    command.add_argument("--manifest", type=Path, required=True); command.add_argument("--root", type=Path)
    command.add_argument("--potcar", type=Path); command.add_argument("--kpoints", type=Path)
    command.add_argument("--replace-kpoints", action="store_true")
    command = sub.add_parser("audit", help="report queued, incomplete, and completed runs")
    command.add_argument("--manifest", type=Path, required=True); command.add_argument("--root", type=Path)
    command.add_argument("--out", type=Path)
    command = sub.add_parser("submit", help="duplicate-safe Slurm submission; preview unless --execute")
    command.add_argument("--manifest", type=Path, required=True); command.add_argument("--root", type=Path)
    command.add_argument("--limit", type=int); command.add_argument("--execute", action="store_true")
    command = sub.add_parser("collect", help="create a checksummed HPC-to-local results archive")
    command.add_argument("--root", type=Path, required=True); command.add_argument("--archive", type=Path, required=True)
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--vaspkit-extract", nargs="+", choices=("charge", "spin", "spin-components"),
                         help="opt-in bulk CHGCAR extraction before archiving")
    command.add_argument("--vaspkit-replace", action="store_true", help="allow VASPKIT to replace existing products")
    command.add_argument("--vaspkit-timeout", type=float, help="per-task timeout in seconds")
    command.add_argument("--tool-registry", type=Path)
    command = sub.add_parser("tool-status", help="locate optional heterostructure-analysis backends")
    command.add_argument("--out", type=Path)
    command.add_argument("--tool-registry", type=Path)
    command = sub.add_parser("tool-config", help="register an independently acquired external executable")
    command.add_argument("tool", choices=("vaspkit",)); command.add_argument("--path", type=Path, required=True)
    command.add_argument("--tool-registry", type=Path)
    command = sub.add_parser("extract-volumetric", help="bulk-extract viewer-ready VASPKIT volumes from CHGCARs")
    command.add_argument("--root", type=Path, required=True)
    command.add_argument("--products", nargs="+", choices=("charge", "spin", "spin-components"),
                         default=("charge", "spin"))
    command.add_argument("--replace", action="store_true"); command.add_argument("--timeout", type=float)
    command.add_argument("--tool-registry", type=Path); command.add_argument("--dry-run", action="store_true")
    command.add_argument("--out", type=Path, help="optional report path (the run root is recorded automatically)")
    command = sub.add_parser("interface-match", help="calculate intrinsic 2D lattice mismatch with hstructpy")
    command.add_argument("substrate", type=Path); command.add_argument("film", type=Path)
    command.add_argument("--substrate-plane"); command.add_argument("--film-plane")
    command.add_argument("--substrate-layers", type=int, default=1); command.add_argument("--film-layers", type=int, default=1)
    command.add_argument("--substrate-swap-axes", action="store_true"); command.add_argument("--film-swap-axes", action="store_true")
    command.add_argument("--substrate-repeats", nargs=2, type=int, default=(1, 1), metavar=("A", "B"))
    command.add_argument("--film-repeats", nargs=2, type=int, default=(1, 1), metavar=("A", "B"))
    command.add_argument("--out", type=Path, required=True, help="JSON report")
    command.add_argument("--marker-out", type=Path, help="optional one-row contour-marker CSV")
    command.add_argument("--marker-plane", help="RuO2 plane used by the contour map")
    command.add_argument("--marker-label", help="label for the optional contour marker")
    command = sub.add_parser("hstruct", help="pass arguments through to the complete hstructpy CLI")
    command.add_argument("arguments", nargs=argparse.REMAINDER)
    command = sub.add_parser("volume-slice", help="render a static VASP volumetric slice")
    command.add_argument("--volume", type=Path, required=True); command.add_argument("--output", type=Path, required=True)
    command.add_argument("--dataset", type=int, default=0); command.add_argument("--center", default="Ru2")
    command.add_argument("--poly-atoms", nargs="+", default=["O2", "O5", "O8", "O9", "O11", "O12"])
    command.add_argument("--plane-atoms", nargs=3, default=["Ru2", "O2", "O5"])
    command.add_argument("--isolevels", nargs="*", type=float, default=[])
    command.add_argument("--grid-points", type=int, default=260); command.add_argument("--padding", type=float, default=0.8)
    command.add_argument("--span", type=float); command.add_argument("--cmap", default="RdBu_r")
    command.add_argument("--value-transform", choices=("raw", "logabs", "signed-log"), default="raw")
    command.add_argument("--log-floor", type=float, default=1.0e-4)
    command.add_argument("--no-symmetric-color", action="store_true")
    command.add_argument("--atom-plane-tolerance", type=float, default=0.15); command.add_argument("--title")
    command.add_argument("--report", type=Path, help="write provenance JSON")
    command.add_argument("--dry-run", action="store_true", help="resolve and report the command without rendering")
    sub.add_parser("help-all", help="print the packaged comprehensive command reference")
    return top


def _main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "help-all":
        print(CLI_REFERENCE.read_text(), end="")
        return 0
    if args.command == "init":
        if args.project.exists() and any(args.project.iterdir()) and not args.ensure_layout:
            raise SystemExit(f"refusing non-empty project: {args.project}")
        for name in ("inputs/structures", "inputs/kpoints", "inputs/markers",
                     "data/raw/accepted_geometries", "data/raw/transfers", "data/processed",
                     "iterations", "plots", "provenance", "templates"):
            (args.project / name).mkdir(parents=True, exist_ok=True)
        values = dict(DEFAULT_CONFIG)
        if args.system: values["system"] = args.system
        if not (args.project / "config.json").exists():
            write_json(args.project / "config.json", values)
        for source in (PACKAGE_ROOT / "templates").iterdir():
            destination = args.project / "templates" / source.name
            if source.is_file() and not destination.exists(): shutil.copy2(source, destination)
        layout = args.project / "PROJECT_LAYOUT.md"
        if not layout.exists():
            shutil.copy2(PACKAGE_ROOT / "data" / "PROJECT_LAYOUT.md", layout)
        verb = "ensured layout for" if args.ensure_layout else "initialized"
        print(f"{verb} {args.project}"); return 0
    if args.command == "propose":
        values = config(args.config); values["iteration"] = args.iteration
        if args.budget is not None: values["budget"] = args.budget
        result = propose(args.input, args.out, values)
    elif args.command == "scaffold-relax":
        values = config(args.config)
        result = scaffold_relax(args.points, args.history, args.source_root, args.out, template_root(args.config),
                                values["system"], args.potcar, args.kpoints,
                                values.get("relax_vasp_command", values.get("vasp_command", "vasp_std")),
                                args.dry_run)
    elif args.command == "scaffold-static":
        values = config(args.config)
        result = scaffold_static(args.relax_manifest, args.relax_results, args.out, template_root(args.config),
                                 values["system"], args.potcar, args.kpoints,
                                 values.get("static_vasp_command", values.get("vasp_command", "vasp_std")),
                                 args.dry_run)
    elif args.command == "scaffold-direct-static":
        values = config(args.config)
        result = scaffold_direct_static(
            args.points, args.history, args.source_root, args.out, template_root(args.config),
            values["system"], args.potcar, args.kpoints,
            values.get("static_vasp_command", values.get("vasp_command", "vasp_std")),
            args.dry_run,
        )
    elif args.command == "ingest":
        values = config(args.config)
        result = ingest(args.results, args.manifest, args.out, values["moment_species"], args.history)
    elif args.command == "plot":
        result = plot(args.input, args.out, args.planes, args.markers)
    elif args.command == "validate":
        result = validate_scaffold(args.manifest, args.root)
    elif args.command == "hydrate":
        result = hydrate_scaffold(args.manifest, args.root, args.potcar, args.kpoints, args.replace_kpoints)
    elif args.command == "audit":
        result = audit_runs(args.manifest, args.root)
        if args.out: write_json(args.out, result)
    elif args.command == "submit":
        result = submit_runs(args.manifest, args.root, args.execute, args.limit)
    elif args.command == "collect":
        extraction = None
        if args.vaspkit_extract:
            extraction = extract_vaspkit_volumes(VaspkitExtractionRequest(
                root=args.root, products=tuple(args.vaspkit_extract), registry=args.tool_registry,
                replace=args.vaspkit_replace, timeout_seconds=args.vaspkit_timeout,
            ), dry_run=args.dry_run)
        result = collect_archive(args.root, args.archive, args.dry_run)
        if extraction is not None: result["vaspkit_extraction"] = extraction
    elif args.command == "tool-status":
        result = tool_status(args.tool_registry)
        if args.out: write_json(args.out, result)
    elif args.command == "tool-config":
        result = configure_external_tool(args.tool, args.path, args.tool_registry)
    elif args.command == "extract-volumetric":
        result = extract_vaspkit_volumes(VaspkitExtractionRequest(
            root=args.root, products=tuple(args.products), registry=args.tool_registry,
            replace=args.replace, timeout_seconds=args.timeout,
        ), dry_run=args.dry_run)
        if args.out: write_json(args.out, result)
    elif args.command == "interface-match":
        if args.marker_out and (not args.marker_plane or not args.marker_label):
            raise SystemExit("--marker-out requires --marker-plane and --marker-label")
        request = InterfaceMatchRequest(
            substrate=args.substrate, film=args.film,
            substrate_plane=args.substrate_plane, film_plane=args.film_plane,
            substrate_layers=args.substrate_layers, film_layers=args.film_layers,
            substrate_swap_axes=args.substrate_swap_axes, film_swap_axes=args.film_swap_axes,
            substrate_repeats=tuple(args.substrate_repeats), film_repeats=tuple(args.film_repeats),
        )
        result = analyze_interface(request)
        if args.marker_out:
            row = marker_from_match(result, args.marker_plane, args.marker_label)
            args.marker_out.parent.mkdir(parents=True, exist_ok=True)
            with args.marker_out.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader(); writer.writerow(row)
            result["marker_csv"] = str(args.marker_out.resolve())
        write_json(args.out, result)
    elif args.command == "hstruct":
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        reply = run_hstructpy(arguments, check=False)
        if reply.stdout: print(reply.stdout, end="")
        if reply.stderr: print(reply.stderr, end="", file=sys.stderr)
        return reply.returncode
    elif args.command == "volume-slice":
        request = VolumeSliceRequest(
            volume=args.volume, output=args.output, dataset=args.dataset, center=args.center,
            poly_atoms=tuple(args.poly_atoms), plane_atoms=tuple(args.plane_atoms),
            isolevels=tuple(args.isolevels), grid_points=args.grid_points, padding=args.padding,
            span=args.span, cmap=args.cmap, value_transform=args.value_transform,
            log_floor=args.log_floor, symmetric_color=not args.no_symmetric_color,
            atom_plane_tolerance=args.atom_plane_tolerance, title=args.title,
        )
        result = render_volume_slice(request, args.dry_run)
        if args.report: write_json(args.report, result)
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (ToolUnavailableError, FileNotFoundError, PermissionError, ValueError) as error:
        print(f"epirefine: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
