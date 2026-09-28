"""Public heterostructure-analysis API and stable adapters.

The adaptive-strain core is native to EpiRefine.  hstructpy and the volumetric
slice viewer remain independently maintained tools and are reached through
explicit, version-reporting adapters rather than copied implementations.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .core import plot, propose, sha256, utc_now, write_json


class ToolUnavailableError(RuntimeError):
    """Raised when an optional companion tool cannot be located."""


@dataclass(frozen=True)
class InterfaceMatchRequest:
    substrate: Path
    film: Path
    substrate_plane: str | None = None
    film_plane: str | None = None
    substrate_layers: int = 1
    film_layers: int = 1
    substrate_swap_axes: bool = False
    film_swap_axes: bool = False
    substrate_repeats: tuple[int, int] = (1, 1)
    film_repeats: tuple[int, int] = (1, 1)


@dataclass(frozen=True)
class VolumeSliceRequest:
    volume: Path
    output: Path
    dataset: int = 0
    center: str = "Ru2"
    poly_atoms: tuple[str, ...] = ("O2", "O5", "O8", "O9", "O11", "O12")
    plane_atoms: tuple[str, str, str] = ("Ru2", "O2", "O5")
    isolevels: tuple[float, ...] = ()
    grid_points: int = 260
    padding: float = 0.8
    span: float | None = None
    cmap: str = "RdBu_r"
    value_transform: str = "raw"
    log_floor: float = 1.0e-4
    symmetric_color: bool = True
    atom_plane_tolerance: float = 0.15
    title: str | None = None


@dataclass(frozen=True)
class AdaptiveProposalRequest:
    static_history: Path
    output_csv: Path
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VaspkitExtractionRequest:
    root: Path
    products: tuple[str, ...] = ("charge", "spin")
    registry: Path | None = None
    replace: bool = False
    timeout_seconds: float | None = None


VASPKIT_PRODUCTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "charge": ("311", ("CHARGE.vasp",)),
    "spin": ("312", ("SPIN.vasp",)),
    "spin-components": ("313", ("SPIN_UP.vasp", "SPIN_DW.vasp")),
}


def tool_registry_path(path: Path | None = None) -> Path:
    """Return the explicit registry, environment override, or user default."""
    if path is not None:
        return path.expanduser().resolve()
    configured = os.environ.get("EPIREFINE_TOOL_REGISTRY")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".config" / "epirefine" / "tools.json"


def _read_tool_registry(path: Path | None = None) -> dict[str, Any]:
    registry = tool_registry_path(path)
    if not registry.is_file():
        return {"schema": "epirefine.tool-registry.v1", "tools": {}}
    value = json.loads(registry.read_text())
    if value.get("schema") != "epirefine.tool-registry.v1" or not isinstance(value.get("tools"), dict):
        raise ValueError(f"invalid EpiRefine tool registry: {registry}")
    return value


def configure_external_tool(name: str, executable: Path,
                            registry: Path | None = None) -> dict[str, Any]:
    """Record an independently acquired executable without copying or installing it."""
    if name != "vaspkit":
        raise ValueError(f"unsupported external tool: {name}")
    resolved = executable.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"external tool is not a file: {resolved}")
    if not os.access(resolved, os.X_OK):
        raise PermissionError(f"external tool is not executable: {resolved}")
    path = tool_registry_path(registry)
    value = _read_tool_registry(path)
    value["tools"][name] = {
        "path": str(resolved), "sha256": sha256(resolved), "configured_utc": utc_now(),
    }
    write_json(path, value)
    return {"schema": "epirefine.tool-config.v1", "tool": name,
            "registry": str(path), **value["tools"][name]}


def resolve_vaspkit(registry: Path | None = None) -> Path:
    """Resolve VASPKIT from an environment override, registry, or PATH."""
    candidates: list[Path] = []
    if os.environ.get("VASPKIT_BIN"):
        candidates.append(Path(os.environ["VASPKIT_BIN"]).expanduser())
    record = _read_tool_registry(registry).get("tools", {}).get("vaspkit", {})
    if record.get("path"):
        candidates.append(Path(record["path"]).expanduser())
    discovered = shutil.which("vaspkit")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise ToolUnavailableError(
        "VASPKIT was not found; acquire it independently, then run "
        "'epirefine tool-config vaspkit --path /absolute/path/to/vaspkit'"
    )


def _candidate_roots(environment: str, relatives: Sequence[Path]) -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get(environment)
    if configured:
        candidates.append(Path(configured).expanduser())
    package = Path(__file__).resolve().parent
    for relative in relatives:
        candidates.extend((package.parent / relative, package.parents[1] / relative))
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def resolve_hstructpy_root() -> Path:
    candidates = _candidate_roots(
        "HSTRUCTPY_ROOT",
        (Path("../grandStrainComparison/hstructpy"), Path("../../grandStrainComparison/hstructpy")),
    )
    for root in candidates:
        if (root / "src" / "hstructpy" / "__init__.py").is_file():
            return root
    raise ToolUnavailableError(
        "hstructpy was not found; set HSTRUCTPY_ROOT to the directory containing src/hstructpy"
    )


def resolve_volume_slice_script() -> Path:
    candidates = _candidate_roots(
        "POLYHEDRON_SLICE_ROOT",
        (
            Path("../spindensityexploration/BondStrainPY/5-21-bondstrainer/polyhedron_slice_tool"),
            Path("../../spindensityexploration/BondStrainPY/5-21-bondstrainer/polyhedron_slice_tool"),
        ),
    )
    for root in candidates:
        script = root if root.name.endswith(".py") else root / "plot_polyhedron_slice.py"
        if script.is_file():
            return script
    raise ToolUnavailableError(
        "polyhedron slice tool was not found; set POLYHEDRON_SLICE_ROOT to its directory or script"
    )


def tool_status(registry: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"schema": "epirefine.tool-status.v1", "created_utc": utc_now()}
    try:
        root = resolve_hstructpy_root()
        version = "unknown"
        init = root / "src" / "hstructpy" / "__init__.py"
        for line in init.read_text().splitlines():
            if line.startswith("__version__"):
                version = line.split("=", 1)[1].strip().strip('"\'')
                break
        result["hstructpy"] = {"available": True, "root": str(root), "version": version}
    except ToolUnavailableError as error:
        result["hstructpy"] = {"available": False, "reason": str(error)}
    try:
        script = resolve_volume_slice_script()
        result["volume_slice"] = {"available": True, "script": str(script),
                                  "sha256": sha256(script)}
    except ToolUnavailableError as error:
        result["volume_slice"] = {"available": False, "reason": str(error)}
    result["adaptive_strain"] = {"available": True, "implementation": "epirefine.core"}
    result["contours"] = {"available": True, "implementation": "epirefine.core.plot"}
    try:
        executable = resolve_vaspkit(registry)
        result["vaspkit"] = {"available": True, "executable": str(executable),
                             "sha256": sha256(executable),
                             "registry": str(tool_registry_path(registry))}
    except ToolUnavailableError as error:
        result["vaspkit"] = {"available": False, "reason": str(error),
                             "registry": str(tool_registry_path(registry))}
    return result


def extract_vaspkit_volumes(request: VaspkitExtractionRequest,
                            dry_run: bool = False) -> dict[str, Any]:
    """Bulk-extract viewer-ready volumes from every CHGCAR below a run root."""
    root = request.root.resolve()
    if not root.is_dir():
        raise ValueError(f"missing run root: {root}")
    unknown = sorted(set(request.products) - set(VASPKIT_PRODUCTS))
    if unknown:
        raise ValueError(f"unsupported VASPKIT products: {', '.join(unknown)}")
    executable = resolve_vaspkit(request.registry)
    rows: list[dict[str, Any]] = []
    for chgcar in sorted(root.rglob("CHGCAR")):
        directory = chgcar.parent
        for product in request.products:
            task, output_names = VASPKIT_PRODUCTS[product]
            outputs = [directory / name for name in output_names]
            existing = [path for path in outputs if path.exists()]
            base = {"run_dir": str(directory.relative_to(root)), "product": product,
                    "task": task, "outputs": output_names}
            if existing and not request.replace:
                state = "skip_existing" if len(existing) == len(outputs) else "conflict_partial_outputs"
                rows.append({**base, "state": state,
                             "existing": [path.name for path in existing]})
                continue
            if dry_run:
                rows.append({**base, "state": "would_extract"})
                continue
            before = {path: (path.stat().st_mtime_ns, path.stat().st_size)
                      for path in outputs if path.exists()}
            try:
                reply = subprocess.run(
                    [str(executable)], cwd=directory, input=task + "\n", text=True,
                    capture_output=True, timeout=request.timeout_seconds, check=False,
                )
            except subprocess.TimeoutExpired as error:
                rows.append({**base, "state": "failed", "reason": f"timeout after {error.timeout}s"})
                continue
            missing = [path.name for path in outputs if not path.is_file() or path.stat().st_size == 0]
            unchanged = [path.name for path in outputs if path in before and
                         (path.stat().st_mtime_ns, path.stat().st_size) == before[path]]
            if reply.returncode or missing or (request.replace and unchanged):
                reason = (f"exit={reply.returncode}; missing={missing}; unchanged={unchanged}; "
                          f"stderr={reply.stderr[-500:].strip()!r}")
                rows.append({**base, "state": "failed", "reason": reason})
                continue
            rows.append({**base, "state": "extracted",
                         "files": [{"path": path.name, "sha256": sha256(path),
                                    "bytes": path.stat().st_size} for path in outputs]})
    states = sorted({row["state"] for row in rows})
    report = {
        "schema": "epirefine.vaspkit-extraction.v1", "created_utc": utc_now(),
        "root": str(root), "products": list(request.products), "dry_run": dry_run,
        "backend": {"name": "vaspkit", "executable": str(executable),
                    "sha256": sha256(executable), "tasks": {
                        product: VASPKIT_PRODUCTS[product][0] for product in request.products}},
        "chgcar_count": sum(1 for _ in root.rglob("CHGCAR")),
        "counts": {state: sum(row["state"] == state for row in rows) for state in states},
        "rows": rows,
    }
    if not dry_run:
        write_json(root / ".epirefine-vaspkit.json", report)
    return report


def analyze_interface(request: InterfaceMatchRequest) -> dict[str, Any]:
    """Return a JSON-serializable intrinsic mismatch report using hstructpy."""
    root = resolve_hstructpy_root()
    source = str(root / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    try:
        hstructpy = importlib.import_module("hstructpy")
        io = importlib.import_module("hstructpy.io")
        orientation = importlib.import_module("hstructpy.orientation")
        substrate = orientation.prepare_surface(
            io.read_structure(request.substrate), request.substrate_plane,
            request.substrate_layers, request.substrate_swap_axes,
        )
        film = orientation.prepare_surface(
            io.read_structure(request.film), request.film_plane,
            request.film_layers, request.film_swap_axes,
        )
        match = hstructpy.analyze_match(
            substrate.atoms.cell.array, film.atoms.cell.array,
            request.substrate_repeats, request.film_repeats,
        )
    except ImportError as error:
        raise ToolUnavailableError(
            "hstructpy was located but its optional dependencies are unavailable; install ASE and NumPy"
        ) from error
    payload = match.as_dict()
    payload.update({
        "schema": "epirefine.interface-match.v1",
        "created_utc": utc_now(),
        "request": {**asdict(request), "substrate": str(request.substrate.resolve()),
                    "film": str(request.film.resolve())},
        "surfaces": {"substrate": substrate.as_dict(), "film": film.as_dict()},
        "backend": {"name": "hstructpy", "version": getattr(hstructpy, "__version__", "unknown"),
                    "root": str(root)},
        "limitation": "Geometric mismatch is not an interface-energy or stability prediction.",
    })
    return payload


def marker_from_match(report: dict[str, Any], plane: str, label: str) -> dict[str, Any]:
    """Convert an interface report into one EpiRefine contour-marker row."""
    return {
        "plane": plane.strip().strip("()"),
        "eps_a_percent": float(report["mismatch_a_percent"]),
        "eps_b_percent": float(report["mismatch_b_percent"]),
        "label": label,
        "source": "hstructpy via epirefine.interface-match.v1",
    }


def run_hstructpy(arguments: Sequence[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run any hstructpy CLI operation through a stable process boundary."""
    root = resolve_hstructpy_root()
    environment = os.environ.copy()
    current = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(root / "src") + (os.pathsep + current if current else "")
    return subprocess.run([sys.executable, "-m", "hstructpy", *arguments], text=True,
                          capture_output=True, check=check, env=environment)


def render_volume_slice(request: VolumeSliceRequest, dry_run: bool = False) -> dict[str, Any]:
    """Render a static volumetric slice through the independently maintained tool."""
    script = resolve_volume_slice_script()
    command = [sys.executable, str(script), "--volume", str(request.volume),
               "--dataset", str(request.dataset), "--center", request.center,
               "--poly-atoms", *request.poly_atoms, "--plane-atoms", *request.plane_atoms,
               "--output", str(request.output), "--grid-points", str(request.grid_points),
               "--padding", str(request.padding), "--cmap", request.cmap,
               "--value-transform", request.value_transform, "--log-floor", str(request.log_floor),
               "--atom-plane-tol", str(request.atom_plane_tolerance)]
    if request.isolevels:
        command += ["--isolevel", ",".join(str(value) for value in request.isolevels)]
    if request.span is not None:
        command += ["--span", str(request.span)]
    if not request.symmetric_color:
        command.append("--no-symmetric-color")
    if request.title:
        command += ["--title", request.title]
    report = {"schema": "epirefine.volume-slice.v1", "created_utc": utc_now(),
              "request": {**asdict(request), "volume": str(request.volume.resolve()),
                          "output": str(request.output.resolve())},
              "backend": {"script": str(script), "sha256": sha256(script)},
              "command": command, "dry_run": dry_run}
    if dry_run:
        return report
    reply = subprocess.run(command, text=True, capture_output=True, check=True)
    outputs = [request.output, request.output.with_suffix(".xyz"), request.output.with_suffix(".txt")]
    missing = [str(path) for path in outputs if not path.is_file()]
    if missing:
        raise RuntimeError(f"volume-slice backend completed without expected outputs: {missing}")
    report["stdout"] = reply.stdout
    report["outputs"] = [{"path": str(path.resolve()), "sha256": sha256(path)} for path in outputs]
    return report


def propose_iteration(request: AdaptiveProposalRequest) -> dict[str, Any]:
    """Stable Python API for adaptive proposal generation."""
    return propose(request.static_history, request.output_csv, dict(request.settings))


def plot_contours(input_csv: Path, output_directory: Path, planes: list[str] | None = None,
                  markers_csv: Path | None = None) -> dict[str, Any]:
    """Stable Python API for static-only contour and sampling-history figures."""
    return plot(input_csv, output_directory, planes, markers_csv)


def write_interface_report(path: Path, report: dict[str, Any]) -> None:
    write_json(path, report)
