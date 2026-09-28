from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import os
import subprocess
import tarfile
import tempfile
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FLOAT = r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?"
FATAL = re.compile(r"VERY BAD NEWS|EDDDAV:|ZBRENT:\s*fatal|internal error", re.I)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def finite(row: dict[str, str], key: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"missing/non-numeric {key}: {row.get(key)!r}") from error
    if not math.isfinite(value):
        raise ValueError(f"non-finite {key}: {value}")
    return value


def percent(row: dict[str, str], axis: str) -> float:
    key = f"eps_{axis}_percent"
    if str(row.get(key, "")).strip():
        return finite(row, key)
    return 100.0 * finite(row, f"eps_{axis}")


def normalize_plane(value: str) -> str:
    return str(value).strip().strip("()")


def accepted_static(row: dict[str, str]) -> bool:
    status = row.get("parse_status", "ok").strip().lower()
    stage = (row.get("calculation_stage") or row.get("data_kind") or row.get("source_type", "")).lower()
    # Imported legacy files must explicitly identify static provenance somewhere.
    return status == "ok" and "static" in stage and bool(row.get("ru_mean_abs_muB", "").strip())


def load_static_points(path: Path) -> dict[str, list[tuple[float, float, float, dict[str, str]]]]:
    grouped: dict[str, list[tuple[float, float, float, dict[str, str]]]] = defaultdict(list)
    seen: set[tuple[str, float, float]] = set()
    for row in read_csv(path):
        if not accepted_static(row):
            continue
        plane = normalize_plane(row.get("plane", ""))
        if not plane:
            continue
        x, y, z = percent(row, "a"), percent(row, "b"), finite(row, "ru_mean_abs_muB")
        key = (plane, round(x, 9), round(y, 9))
        if key in seen:
            raise ValueError(f"duplicate accepted static coordinate: {key}")
        seen.add(key)
        grouped[plane].append((x, y, z, row))
    if not grouped:
        raise ValueError("no rows with parse_status=ok and explicit static provenance")
    return grouped


def triangle_geometry(vertices: Any) -> tuple[float, float, float]:
    import numpy as np

    lengths = [float(np.linalg.norm(vertices[i] - vertices[j])) for i, j in ((0, 1), (1, 2), (2, 0))]
    h = max(lengths)
    first, second = vertices[1] - vertices[0], vertices[2] - vertices[0]
    area = abs(float(first[0] * second[1] - first[1] * second[0])) / 2.0
    quality = 4.0 * math.sqrt(3.0) * area / max(sum(length * length for length in lengths), 1e-30)
    return h, area, quality


def maximin_in_triangle(vertices: Any, existing: Any, divisions: int) -> tuple[Any, float]:
    import numpy as np

    candidates = []
    for i in range(1, divisions - 1):
        for j in range(1, divisions - i):
            k = divisions - i - j
            if k > 0:
                candidates.append((i * vertices[0] + j * vertices[1] + k * vertices[2]) / divisions)
    if not candidates:
        point = vertices.mean(axis=0)
        return point, float(np.min(np.linalg.norm(existing - point, axis=1)))
    array = np.asarray(candidates)
    distances = np.min(np.linalg.norm(array[:, None, :] - existing[None, :, :], axis=2), axis=1)
    index = int(np.argmax(distances))
    return array[index], float(distances[index])


def propose(input_csv: Path, output_csv: Path, settings: dict[str, Any]) -> dict[str, Any]:
    try:
        import numpy as np
        from scipy.spatial import ConvexHull, Delaunay
    except ImportError as error:
        raise SystemExit("proposal generation requires numpy and scipy") from error

    groups = load_static_points(input_csv)
    requested_planes = {normalize_plane(value) for value in settings.get("planes", groups)}
    groups = {plane: rows for plane, rows in groups.items() if plane in requested_planes}
    if not groups:
        raise ValueError("none of the configured planes occur in accepted static data")
    budget = int(settings["budget"])
    low = float(settings["low_moment"])
    high = float(settings["high_moment"])
    min_span = float(settings["min_response_span"])
    max_h = float(settings["max_unresolved_diameter_percent"])
    min_quality = float(settings["min_triangle_quality"])
    boundary_spacing = float(settings["boundary_spacing_percent"])
    pocket_spacing = float(settings["pocket_spacing_percent"])
    divisions = int(settings["barycentric_divisions"])
    bounds = [float(value) for value in settings["strain_bounds_percent"]]
    candidates: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    for plane, records in sorted(groups.items()):
        if len(records) < 3:
            metrics[plane] = {"status": "need at least three accepted static points"}
            continue
        points = np.asarray([(row[0], row[1]) for row in records], dtype=float)
        values = np.asarray([row[2] for row in records], dtype=float)
        triangulation = Delaunay(points)
        hull_vertices = set(int(value) for value in ConvexHull(points).vertices)
        edge_graph: dict[int, set[int]] = defaultdict(set)
        for simplex in triangulation.simplices:
            for left, right in ((simplex[0], simplex[1]), (simplex[1], simplex[2]), (simplex[2], simplex[0])):
                edge_graph[int(left)].add(int(right)); edge_graph[int(right)].add(int(left))

        low_vertices = {index for index, value in enumerate(values) if value <= low}
        components: list[set[int]] = []
        remaining = set(low_vertices)
        while remaining:
            seed = remaining.pop(); component = {seed}; queue = deque([seed])
            while queue:
                current = queue.popleft()
                for neighbor in edge_graph[current] & remaining & low_vertices:
                    remaining.remove(neighbor); component.add(neighbor); queue.append(neighbor)
            outer = set().union(*(edge_graph[index] for index in component)) - component
            if component.isdisjoint(hull_vertices) and outer and min(values[index] for index in outer) >= high:
                components.append(component)

        triangle_rows = []
        for index, simplex in enumerate(triangulation.simplices):
            vertex_ids = [int(value) for value in simplex]
            vertices = points[vertex_ids]
            local = values[vertex_ids]
            h, area, quality = triangle_geometry(vertices)
            span = float(local.max() - local.min())
            crosses = float(local.min()) <= low and float(local.max()) >= high
            point, distance = maximin_in_triangle(vertices, points, divisions)
            gradient = span / max(h, 1e-12)
            triangle_rows.append({"index": index, "vertices": vertex_ids, "point": point,
                                  "h": h, "area": area, "quality": quality, "span": span,
                                  "crosses": crosses, "gradient": gradient, "distance": distance})

        for component_id, component in enumerate(components, 1):
            adjacent = [item for item in triangle_rows if component.intersection(item["vertices"])]
            adjacent.sort(key=lambda item: (item["distance"], item["gradient"]), reverse=True)
            if adjacent:
                item = adjacent[0]
                candidates.append({**item, "plane": plane, "channel": "zero_pocket_confirmation",
                                   "component": component_id, "spacing": pocket_spacing,
                                   "priority": 1e6 + item["distance"]})

        unresolved_count = 0
        for item in triangle_rows:
            response = item["crosses"] or item["span"] >= min_span
            if item["h"] >= max_h and response and item["quality"] >= min_quality:
                unresolved_count += 1
                score = item["gradient"] * item["h"] * math.sqrt(item["quality"])
                candidates.append({**item, "plane": plane, "channel": "boundary_gradient",
                                   "component": None, "spacing": boundary_spacing, "priority": score})
        metrics[plane] = {"accepted_static_points": len(points), "triangles": len(triangle_rows),
                          "enclosed_low_components": len(components), "unresolved_triangles": unresolved_count,
                          "triangle_quality_definition": "4*sqrt(3)*area/sum(edge_length^2)"}

    candidates.sort(key=lambda item: (item["priority"], item["distance"], item["plane"]), reverse=True)
    selected: list[dict[str, Any]] = []
    existing = {plane: [(x, y) for x, y, _, _ in rows] for plane, rows in groups.items()}
    seen_triangles: set[tuple[str, int]] = set()
    for item in candidates:
        if len(selected) >= budget:
            break
        point = tuple(float(value) for value in item["point"])
        if not (bounds[0] <= point[0] <= bounds[1] and bounds[0] <= point[1] <= bounds[1]):
            continue
        if item["distance"] < item["spacing"]:
            continue
        if any(other["plane"] == item["plane"] and math.dist(point, other["point"]) < item["spacing"] for other in selected):
            continue
        triangle_key = (item["plane"], item["index"])
        if item["channel"] == "boundary_gradient" and triangle_key in seen_triangles:
            continue
        selected.append({**item, "point": point})
        seen_triangles.add(triangle_key)

    rows = []
    for rank, item in enumerate(selected, 1):
        x, y = item["point"]
        rows.append({"plane": item["plane"], "eps_a_percent": f"{x:.10f}",
                     "eps_b_percent": f"{y:.10f}", "eps_a": f"{x / 100:.12f}",
                     "eps_b": f"{y / 100:.12f}", "proposal_rank": rank,
                     "acquisition_channel": item["channel"], "source_triangle": item["index"],
                     "triangle_diameter_percent": f"{item['h']:.10g}",
                     "triangle_quality": f"{item['quality']:.10g}",
                     "response_span_muB_per_Ru": f"{item['span']:.10g}",
                     "gradient_muB_per_Ru_per_percent": f"{item['gradient']:.10g}",
                     "nearest_existing_percent": f"{item['distance']:.10g}",
                     "pocket_component": item["component"] or "", "source_iteration": settings["iteration"]})
    fields = ["plane", "eps_a_percent", "eps_b_percent", "eps_a", "eps_b", "proposal_rank",
              "acquisition_channel", "source_triangle", "triangle_diameter_percent", "triangle_quality",
              "response_span_muB_per_Ru", "gradient_muB_per_Ru_per_percent", "nearest_existing_percent",
              "pocket_component", "source_iteration"]
    write_csv(output_csv, rows, fields)
    report = {"schema": "epirefine.proposal.v1", "created_utc": utc_now(), "input": str(input_csv.resolve()),
              "input_sha256": sha256(input_csv), "output_sha256": sha256(output_csv),
              "method": "Delaunay maximin refinement of unresolved response triangles and enclosed low-moment components",
              "settings": settings, "metrics": metrics, "proposed_points": len(rows),
              "randomness": "none; deterministic ordering (seed is retained only as a project provenance field)",
              "important_limitation": "This acquisition rule allocates calculations; it is not an interpolation error bound or proof of a phase boundary."}
    write_json(output_csv.with_suffix(".json"), report)
    return report


def parse_poscar(path: Path) -> dict[str, Any]:
    lines = path.read_text().splitlines(keepends=True)
    if len(lines) < 9:
        raise ValueError(f"short POSCAR/CONTCAR: {path}")
    scale = float(lines[1].split()[0])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError(f"only positive POSCAR scale factors are supported: {path}")
    cell = [[scale * float(value) for value in lines[index].split()[:3]] for index in range(2, 5)]
    cursor = 5
    tokens = lines[cursor].split()
    if all(token.lstrip("+-").isdigit() for token in tokens):
        species = [f"species_{index + 1}" for index in range(len(tokens))]
        counts = [int(value) for value in tokens]
    else:
        species = tokens; cursor += 1; counts = [int(value) for value in lines[cursor].split()]
    cursor += 1
    if lines[cursor].strip().lower().startswith("s"):
        cursor += 1
    if not lines[cursor].strip().lower().startswith("d"):
        raise ValueError(f"EpiRefine requires Direct coordinates for safe lattice rescaling: {path}")
    if sum(counts) <= 0 or len(lines) < cursor + 1 + sum(counts):
        raise ValueError(f"invalid species counts in {path}")
    return {"lines": lines, "cell": cell, "species": species, "counts": counts, "coordinate_line": cursor}


def strained_poscar(source: Path, old_a_percent: float, old_b_percent: float,
                    new_a_percent: float, new_b_percent: float) -> tuple[str, dict[str, float]]:
    parsed = parse_poscar(source)
    factors = [(100.0 + new_a_percent) / (100.0 + old_a_percent),
               (100.0 + new_b_percent) / (100.0 + old_b_percent)]
    if min(factors) <= 0:
        raise ValueError("strain factors must preserve positive lattice lengths")
    cell = [list(vector) for vector in parsed["cell"]]
    cell[0] = [value * factors[0] for value in cell[0]]
    cell[1] = [value * factors[1] for value in cell[1]]
    lines = list(parsed["lines"])
    lines[1] = "1.0\n"
    for index, vector in enumerate(cell):
        lines[2 + index] = "  ".join(f"{value:.16f}" for value in vector) + "\n"
    norm = lambda vector: math.sqrt(sum(value * value for value in vector))
    return "".join(lines), {"target_a_A": norm(cell[0]), "target_b_A": norm(cell[1]),
                             "scale_a": factors[0], "scale_b": factors[1]}


def template_text(package_root: Path, name: str, replacements: dict[str, str]) -> str:
    path = package_root / "templates" / name
    if not path.is_file() and name.endswith(".job.slurm"):
        path = package_root / "templates" / "job.slurm"
    text = path.read_text()
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    unresolved = re.findall(r"{{[^}]+}}", text)
    if unresolved:
        raise ValueError(f"unresolved template fields in {name}: {unresolved}")
    return text


def resolve_geometry(row: dict[str, str], source_root: Path) -> Path:
    options = []
    for key in ("relax_contcar", "geometry_path", "contcar", "relax_source_relpath"):
        if row.get(key):
            path = Path(row[key]); path = path if path.is_absolute() else source_root / path
            options.append(path if path.name in {"POSCAR", "CONTCAR"} else path / "CONTCAR")
    source_relpath = row.get("source_relpath", "")
    if source_relpath:
        path = Path(source_relpath); path = path if path.is_absolute() else source_root / path
        if path.name in {"OUTCAR", "OSZICAR"}:
            options.extend((path.parent / "POSCAR", path.parent / "CONTCAR"))
    run_dir = row.get("relax_run_dir") or row.get("run_dir")
    if run_dir:
        relative = Path(run_dir)
        options.append(source_root / relative / "CONTCAR")
        options.append(source_root / Path(str(relative).replace("static_stage", "relax_stage")) / "CONTCAR")
    for option in options:
        if option.is_file():
            return option
    if run_dir:
        suffix = Path(run_dir).name
        matches = [path for path in source_root.rglob("CONTCAR") if path.parent.name == suffix]
        if len(matches) == 1:
            return matches[0]
    raise FileNotFoundError(f"no unambiguous CONTCAR for source row {row.get('run_dir', '')!r}")


def _copy_input(explicit: Path | None, source_dir: Path, name: str, destination: Path) -> str | None:
    origin = explicit if explicit else source_dir / name
    if origin and origin.is_file():
        shutil.copy2(origin, destination / name)
        return sha256(destination / name)
    return None


def scaffold_relax(points_csv: Path, history_csv: Path, source_root: Path, out: Path,
                   package_root: Path, system: str, potcar: Path | None, kpoints: Path | None,
                   vasp_command: str, dry_run: bool = False) -> dict[str, Any]:
    return _scaffold_points(points_csv, history_csv, source_root, out, package_root,
                            system, potcar, kpoints, vasp_command, "relax", dry_run)


def scaffold_direct_static(points_csv: Path, history_csv: Path, source_root: Path, out: Path,
                           package_root: Path, system: str, potcar: Path | None,
                           kpoints: Path | None, vasp_command: str,
                           dry_run: bool = False) -> dict[str, Any]:
    """Create statics directly from strained accepted geometries, without relaxation."""
    return _scaffold_points(points_csv, history_csv, source_root, out, package_root,
                            system, potcar, kpoints, vasp_command, "direct_static", dry_run)


def _scaffold_points(points_csv: Path, history_csv: Path, source_root: Path, out: Path,
                     package_root: Path, system: str, potcar: Path | None,
                     kpoints: Path | None, vasp_command: str, mode: str,
                     dry_run: bool = False) -> dict[str, Any]:
    if mode not in {"relax", "direct_static"}:
        raise ValueError(f"unsupported point-scaffold mode: {mode}")
    if out.exists():
        raise FileExistsError(f"refusing existing output directory: {out}")
    proposals = read_csv(points_csv)
    groups = load_static_points(history_csv)
    plan = []
    seen: set[tuple[str, float, float]] = set()
    for index, proposal in enumerate(proposals, 1):
        plane = normalize_plane(proposal.get("plane", "")); x, y = percent(proposal, "a"), percent(proposal, "b")
        key = (plane, round(x, 9), round(y, 9))
        if key in seen or plane not in groups:
            raise ValueError(f"duplicate proposal or plane without accepted static history: {key}")
        seen.add(key)
        source = min(groups[plane], key=lambda item: (item[0] - x) ** 2 + (item[1] - y) ** 2)
        geometry = resolve_geometry(source[3], source_root)
        name = f"p{index:04d}_epsA{x:+.6f}_epsB{y:+.6f}"
        run_rel = Path(plane) / name
        record = {"id": name, "plane": plane, "eps_a_percent": x, "eps_b_percent": y,
                  "run_dir": str(run_rel), "source_run_dir": source[3].get("run_dir", ""),
                  "source_eps_a_percent": source[0], "source_eps_b_percent": source[1],
                  "geometry_source": str(geometry.resolve()), "geometry_sha256": sha256(geometry),
                  "proposal": proposal}
        if mode == "direct_static":
            record.update({
                "source_iteration": proposal.get("source_iteration", ""),
                "geometry_protocol": "direct_static",
                "geometry_source_method": "affine_in_plane_strain_from_nearest_accepted_static_geometry",
                "ionic_relaxation_performed": False,
                "sample_metadata": {"geometry_protocol": "direct_static", "relaxed_at_target": False},
            })
        plan.append(record)
        if dry_run:
            continue
        destination = out / run_rel; destination.mkdir(parents=True)
        text, lattice = strained_poscar(geometry, source[0], source[1], x, y)
        (destination / "POSCAR").write_text(text)
        template_stage = "static" if mode == "direct_static" else "relax"
        (destination / "INCAR").write_text(template_text(package_root, template_stage + ".INCAR", {"SYSTEM": system}))
        (destination / "job.slurm").write_text(template_text(
            package_root, template_stage + ".job.slurm",
            {"JOB_NAME": name + ("_static" if mode == "direct_static" else "_relax"),
             "VASP_COMMAND": vasp_command}))
        (destination / "job.slurm").chmod(0o755)
        hashes = {name_: sha256(destination / name_) for name_ in ("POSCAR", "INCAR", "job.slurm")}
        hashes["KPOINTS"] = _copy_input(kpoints, geometry.parent, "KPOINTS", destination)
        hashes["POTCAR"] = _copy_input(potcar, geometry.parent, "POTCAR", destination)
        if hashes["KPOINTS"] is None:
            shutil.copy2(package_root / "templates" / "KPOINTS", destination / "KPOINTS"); hashes["KPOINTS"] = sha256(destination / "KPOINTS")
        record["lattice"] = lattice; record["file_sha256"] = hashes
        record["ready_for_submission"] = hashes["POTCAR"] is not None
        write_json(destination / ".epirefine-stage.json",
                   {"stage": "static" if mode == "direct_static" else "relax", "id": name,
                    "construction_mode": mode})
        if hashes["POTCAR"] is None:
            (destination / "POTCAR_REQUIRED").write_text("Supply a licensed POTCAR and record its checksum before submission.\n")
    stage = "static" if mode == "direct_static" else "relax"
    schema = "epirefine.static-manifest.v1" if mode == "direct_static" else "epirefine.relax-manifest.v1"
    manifest = {"schema": schema, "stage": stage, "construction_mode": mode,
                "created_utc": utc_now(),
                "points_csv": str(points_csv.resolve()), "points_sha256": sha256(points_csv),
                "history_csv": str(history_csv.resolve()), "history_sha256": sha256(history_csv),
                "source_root": str(source_root.resolve()), "dry_run": dry_run, "runs": plan}
    if mode == "direct_static":
        manifest["rejected_relaxations"] = []
        manifest["scientific_guard"] = (
            "No ionic relaxation was performed at target strain. Treat this as a fixed-geometry "
            "response surface and do not silently merge it with relaxed-at-target data."
        )
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / ("static_manifest.json" if mode == "direct_static" else "relax_manifest.json"), manifest)
    return manifest


def find_by_suffix(root: Path, relative: str, filename: str) -> Path | None:
    direct = root / relative / filename
    if direct.is_file():
        return direct
    suffix = Path(relative).name
    matches = [path for path in root.rglob(filename) if path.parent.name == suffix]
    return matches[0] if len(matches) == 1 else None


def relax_complete(outcar: Path, contcar: Path) -> tuple[bool, str]:
    if not outcar.is_file() or not contcar.is_file() or contcar.stat().st_size == 0:
        return False, "missing OUTCAR or CONTCAR"
    text = outcar.read_text(errors="replace")
    if FATAL.search(text):
        return False, "fatal signature"
    if "reached required accuracy" not in text.lower():
        return False, "ionic convergence marker absent"
    if "General timing and accounting" not in text:
        return False, "normal termination marker absent"
    try:
        parse_poscar(contcar)
    except ValueError as error:
        return False, str(error)
    return True, "ok"


def scaffold_static(relax_manifest: Path, relax_results: Path, out: Path, package_root: Path,
                    system: str, potcar: Path | None, kpoints: Path | None,
                    vasp_command: str, dry_run: bool = False) -> dict[str, Any]:
    if out.exists():
        raise FileExistsError(f"refusing existing output directory: {out}")
    source_manifest = read_json(relax_manifest)
    records = []
    rejected = []
    for source in source_manifest.get("runs", []):
        outcar = find_by_suffix(relax_results, source["run_dir"], "OUTCAR")
        contcar = find_by_suffix(relax_results, source["run_dir"], "CONTCAR")
        good, reason = relax_complete(outcar or Path("/nonexistent"), contcar or Path("/nonexistent"))
        if not good:
            rejected.append({"id": source["id"], "reason": reason}); continue
        run_rel = Path(source["plane"]) / source["id"]
        record = {"id": source["id"], "plane": source["plane"],
                  "eps_a_percent": source["eps_a_percent"], "eps_b_percent": source["eps_b_percent"],
                  "run_dir": str(run_rel), "relax_run_dir": source["run_dir"],
                  "source_iteration": source.get("proposal", {}).get("source_iteration", ""),
                  "relax_outcar_sha256": sha256(outcar), "relax_contcar_sha256": sha256(contcar),
                  "geometry_protocol": "relaxed_static", "ionic_relaxation_performed": True,
                  "sample_metadata": {"geometry_protocol": "relaxed_static",
                                      "relaxed_at_target": True}}
        records.append(record)
        if dry_run:
            continue
        destination = out / run_rel; destination.mkdir(parents=True)
        shutil.copy2(contcar, destination / "POSCAR")
        (destination / "INCAR").write_text(template_text(package_root, "static.INCAR", {"SYSTEM": system}))
        (destination / "job.slurm").write_text(template_text(package_root, "static.job.slurm", {"JOB_NAME": source["id"] + "_static", "VASP_COMMAND": vasp_command}))
        (destination / "job.slurm").chmod(0o755)
        hashes = {name: sha256(destination / name) for name in ("POSCAR", "INCAR", "job.slurm")}
        source_dir = contcar.parent
        hashes["KPOINTS"] = _copy_input(kpoints, source_dir, "KPOINTS", destination)
        hashes["POTCAR"] = _copy_input(potcar, source_dir, "POTCAR", destination)
        if hashes["KPOINTS"] is None:
            shutil.copy2(package_root / "templates" / "KPOINTS", destination / "KPOINTS"); hashes["KPOINTS"] = sha256(destination / "KPOINTS")
        record["file_sha256"] = hashes; record["ready_for_submission"] = hashes["POTCAR"] is not None
        write_json(destination / ".epirefine-stage.json", {"stage": "static", "id": source["id"]})
        if hashes["POTCAR"] is None:
            (destination / "POTCAR_REQUIRED").write_text("Supply a licensed POTCAR and record its checksum before submission.\n")
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "epirefine.static-manifest.v1", "stage": "static", "created_utc": utc_now(),
                "relax_manifest": str(relax_manifest.resolve()), "relax_manifest_sha256": sha256(relax_manifest),
                "relax_results": str(relax_results.resolve()), "dry_run": dry_run, "runs": records,
                "rejected_relaxations": rejected,
                "scientific_guard": "Only normal-terminating, ionically converged relaxations with parseable CONTCARs were admitted."}
    write_json(out / "static_manifest.json", manifest)
    return manifest


def parse_magnetization(outcar: Path, poscar: Path, species: list[str]) -> dict[str, Any]:
    parsed = parse_poscar(poscar)
    target = {name.lower() for name in species}
    indices = []
    cursor = 1
    for name, count in zip(parsed["species"], parsed["counts"]):
        if name.lower() in target:
            indices.extend(range(cursor, cursor + count))
        cursor += count
    if not indices:
        raise ValueError(f"none of moment species {species} occur in {poscar}")
    text = outcar.read_text(errors="replace")
    heads = list(re.finditer(r"^\s*magnetization\s*\(x\)\s*$", text, re.M | re.I))
    values: dict[int, float] = {}
    if heads:
        lines = text[heads[-1].start():].splitlines()
        table = next((index + 1 for index, line in enumerate(lines[:20]) if "# of ion" in line.lower()), None)
        if table is not None:
            for line in lines[table:]:
                match = re.match(rf"^\s*(\d+)\s+(?:{FLOAT}\s+){{3,}}({FLOAT})\s*$", line)
                if match:
                    values[int(match.group(1))] = float(match.group(2))
                elif values:
                    break
    energies = re.findall(rf"energy\(sigma->0\)\s*=\s*({FLOAT})", text)
    complete = ("General timing and accounting" in text and not FATAL.search(text)
                and all(index in values for index in indices) and bool(energies))
    return {"complete": complete,
            "ru_mean_abs_muB": sum(abs(values[index]) for index in indices) / len(indices) if complete else None,
            "energy_sigma0_eV": float(energies[-1]) if complete else None,
            "moment_species": species, "moment_site_count": len(indices), "all_site_moments": values}


def ingest(results_root: Path, manifest_path: Path, output_csv: Path, species: list[str],
           history: Path | None = None) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    if manifest.get("stage") != "static":
        raise ValueError("ingest requires an epirefine static manifest; relaxation moments are never final data")
    incoming = []
    for record in manifest.get("runs", []):
        outcar = find_by_suffix(results_root, record["run_dir"], "OUTCAR")
        poscar = find_by_suffix(results_root, record["run_dir"], "POSCAR")
        if outcar is None or poscar is None:
            parsed = {"complete": False, "ru_mean_abs_muB": None, "energy_sigma0_eV": None,
                      "moment_species": species, "moment_site_count": 0}
            digest = ""
        else:
            parsed = parse_magnetization(outcar, poscar, species); digest = sha256(outcar)
        incoming.append({"plane": record["plane"], "eps_a_percent": record["eps_a_percent"],
                         "eps_b_percent": record["eps_b_percent"],
                         "eps_a": float(record["eps_a_percent"]) / 100,
                         "eps_b": float(record["eps_b_percent"]) / 100,
                         "ru_mean_abs_muB": "" if not parsed["complete"] else parsed["ru_mean_abs_muB"],
                         "energy_sigma0_eV": "" if not parsed["complete"] else parsed["energy_sigma0_eV"],
                         "parse_status": "ok" if parsed["complete"] else "incomplete",
                         "calculation_stage": "static", "data_kind": "static",
                         "source_iteration": record.get("source_iteration", manifest_path.parent.name),
                         "run_dir": record["run_dir"], "outcar_sha256": digest,
                         "geometry_path": str(poscar.resolve()) if poscar else "",
                         "relax_run_dir": record.get("relax_run_dir", ""),
                         "geometry_protocol": record.get("geometry_protocol", "unknown"),
                         "ionic_relaxation_performed": record.get("ionic_relaxation_performed", ""),
                         "moment_species": ",".join(species), "moment_site_count": parsed["moment_site_count"],
                         "sample_metadata_json": json.dumps(record.get("sample_metadata", {}), sort_keys=True)})
    old = read_csv(history) if history else []
    by_coordinate: dict[tuple[str, float, float], dict[str, Any]] = {}
    for row in old + incoming:
        key = (normalize_plane(row.get("plane", "")), round(percent(row, "a"), 9), round(percent(row, "b"), 9))
        if key in by_coordinate:
            if row.get("outcar_sha256") and row.get("outcar_sha256") == by_coordinate[key].get("outcar_sha256"):
                continue
            raise ValueError(f"duplicate coordinate with different provenance: {key}")
        by_coordinate[key] = row
    combined = list(by_coordinate.values())
    fields = ["plane", "eps_a_percent", "eps_b_percent", "eps_a", "eps_b", "ru_mean_abs_muB",
              "energy_sigma0_eV", "parse_status", "calculation_stage", "data_kind", "source_iteration",
              "run_dir", "outcar_sha256", "geometry_path", "relax_run_dir", "moment_species",
              "geometry_protocol", "ionic_relaxation_performed", "moment_site_count",
              "sample_metadata_json"]
    fields += sorted({key for row in combined for key in row} - set(fields))
    write_csv(output_csv, combined, fields)
    report = {"schema": "epirefine.ingest.v1", "created_utc": utc_now(), "static_manifest": str(manifest_path.resolve()),
              "static_manifest_sha256": sha256(manifest_path), "rows_total": len(combined),
              "incoming_ok": sum(row["parse_status"] == "ok" for row in incoming),
              "incoming_incomplete": sum(row["parse_status"] != "ok" for row in incoming),
              "output_sha256": sha256(output_csv), "static_only": True}
    write_json(output_csv.with_suffix(".json"), report)
    return report


def plot(input_csv: Path, out: Path, planes: list[str] | None = None,
         markers_csv: Path | None = None) -> dict[str, Any]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.tri as mtri
        import numpy as np
    except ImportError as error:
        raise SystemExit("plotting requires numpy and matplotlib") from error
    groups = load_static_points(input_csv)
    selected_planes = planes or sorted(groups)
    missing = [plane for plane in selected_planes if plane not in groups]
    if missing:
        raise ValueError(f"requested planes absent from accepted static data: {missing}")
    values = [row[2] for plane in selected_planes for row in groups[plane]]
    vmin, vmax = min(0.0, min(values)), max(values)
    if math.isclose(vmin, vmax):
        vmax = vmin + 1e-9
    levels = np.linspace(vmin, vmax, 41)
    markers: dict[str, list[dict[str, str]]] = defaultdict(list)
    if markers_csv:
        for row in read_csv(markers_csv):
            if row.get("plot_on_2d_contour", "yes").strip().lower() in {"no", "false", "0"}:
                continue
            plane = normalize_plane(row.get("plane") or row.get("ruo2_plane", ""))
            if plane:
                markers[plane].append(row)
    out.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, len(selected_planes), figsize=(5 * len(selected_planes), 4.8),
                               sharex=True, sharey=True, squeeze=False, constrained_layout=True)
    last = None
    for axis, plane in zip(axes[0], selected_planes):
        records = groups[plane]
        x = np.asarray([row[0] for row in records]); y = np.asarray([row[1] for row in records]); z = np.asarray([row[2] for row in records])
        if len(records) >= 3:
            tri = mtri.Triangulation(x, y); last = axis.tricontourf(tri, z, levels=levels, cmap="magma", extend="both")
        else:
            last = axis.scatter(x, y, c=z, cmap="magma", vmin=vmin, vmax=vmax)
        axis.scatter(x, y, s=7, c="white", edgecolors="black", linewidths=.2, alpha=.8)
        for marker in markers.get(plane, []):
            marker_x, marker_y = percent(marker, "a"), percent(marker, "b")
            axis.scatter([marker_x], [marker_y], s=34, facecolors="white", edgecolors="black", zorder=8)
            label = marker.get("label", "").strip()
            if not label and marker.get("substrate"):
                label = marker["substrate"].strip() + marker.get("substrate_plane", "").strip()
            if label:
                axis.annotate(label, (marker_x, marker_y), xytext=(4, 4), textcoords="offset points",
                              fontsize=7, bbox={"facecolor": "white", "alpha": .8,
                                                "edgecolor": "none", "pad": 1})
        axis.set(title=f"({plane})  N={len(records)}", xlabel="strain A (%)", ylabel="strain B (%)")
        axis.set_aspect("equal", adjustable="box")
    figure.colorbar(last, ax=list(axes[0]), label="mean |moment| (μB/selected atom)", shrink=.85)
    figure.suptitle("Static-only epitaxial-strain response")
    for suffix in ("png", "pdf"):
        figure.savefig(out / f"strain_contours_overview.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(figure)

    figure, axes = plt.subplots(1, len(selected_planes), figsize=(5 * len(selected_planes), 4.8),
                               sharex=True, sharey=True, squeeze=False, constrained_layout=True)
    iterations = sorted({row[3].get("source_iteration", "unknown") for plane in selected_planes for row in groups[plane]})
    palette = {iteration: index for index, iteration in enumerate(iterations)}
    for axis, plane in zip(axes[0], selected_planes):
        records = groups[plane]
        for iteration in iterations:
            subset = [row for row in records if row[3].get("source_iteration", "unknown") == iteration]
            if subset:
                axis.scatter([row[0] for row in subset], [row[1] for row in subset], s=12,
                             label=iteration, color=plt.cm.tab20(palette[iteration] % 20))
        axis.set(title=f"({plane})", xlabel="strain A (%)", ylabel="strain B (%)"); axis.set_aspect("equal")
    axes[0][-1].legend(fontsize=7, loc="best")
    figure.suptitle("Accepted static sampling history")
    for suffix in ("png", "pdf"):
        figure.savefig(out / f"sampling_history.{suffix}", dpi=250, bbox_inches="tight")
    plt.close(figure)
    report = {"schema": "epirefine.plot.v1", "created_utc": utc_now(), "input": str(input_csv.resolve()),
              "input_sha256": sha256(input_csv), "planes": selected_planes,
              "counts": {plane: len(groups[plane]) for plane in selected_planes},
              "interpolation": "piecewise-linear Delaunay triangulation", "static_only": True,
              "color_range": [vmin, vmax],
              "markers_csv": str(markers_csv.resolve()) if markers_csv else None,
              "markers_sha256": sha256(markers_csv) if markers_csv else None}
    write_json(out / "plot_metadata.json", report)
    return report


def resolve_run_directory(root: Path, relative: str) -> Path | None:
    direct = root / relative
    if direct.is_dir():
        return direct
    name = Path(relative).name
    matches = [path for path in root.rglob(name) if path.is_dir()]
    return matches[0] if len(matches) == 1 else None


def validate_scaffold(manifest_path: Path, root: Path | None = None) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    stage = manifest.get("stage")
    if stage not in {"relax", "static"}:
        raise ValueError("manifest stage must be relax or static")
    base = root or manifest_path.parent
    issues = []
    coordinates = set()
    ids = set()
    ready = 0
    for record in manifest.get("runs", []):
        key = (normalize_plane(record.get("plane", "")), round(float(record["eps_a_percent"]), 9),
               round(float(record["eps_b_percent"]), 9))
        if key in coordinates:
            issues.append({"id": record.get("id"), "issue": "duplicate coordinate"})
        coordinates.add(key)
        if record.get("id") in ids:
            issues.append({"id": record.get("id"), "issue": "duplicate run id"})
        ids.add(record.get("id"))
        directory = resolve_run_directory(base, record["run_dir"])
        if directory is None:
            issues.append({"id": record.get("id"), "issue": "run directory absent or ambiguous"}); continue
        hashes = record.get("file_sha256", {})
        for name, expected in hashes.items():
            path = directory / name
            if expected is None:
                issues.append({"id": record.get("id"), "issue": f"{name} not supplied"})
            elif not path.is_file() or sha256(path) != expected:
                issues.append({"id": record.get("id"), "issue": f"{name} missing or checksum mismatch"})
        if record.get("ready_for_submission") and all((directory / name).is_file() for name in ("POSCAR", "INCAR", "KPOINTS", "POTCAR", "job.slurm")):
            ready += 1
    return {"schema": "epirefine.validation.v1", "stage": stage, "manifest": str(manifest_path.resolve()),
            "manifest_sha256": sha256(manifest_path), "run_count": len(manifest.get("runs", [])),
            "ready_count": ready, "issues": issues, "valid": not issues}


def hydrate_scaffold(manifest_path: Path, root: Path | None, potcar: Path | None,
                     kpoints: Path | None, replace_kpoints: bool = False) -> dict[str, Any]:
    """Add licensed/site-specific inputs after transfer and update recorded hashes."""
    if not potcar and not kpoints:
        raise ValueError("provide --potcar and/or --kpoints")
    for path in (potcar, kpoints):
        if path is not None and not path.is_file():
            raise FileNotFoundError(path)
    before = sha256(manifest_path); manifest = read_json(manifest_path); base = root or manifest_path.parent
    changed = []
    for record in manifest.get("runs", []):
        directory = resolve_run_directory(base, record["run_dir"])
        if directory is None:
            raise FileNotFoundError(f"run directory absent or ambiguous: {record['run_dir']}")
        hashes = record.setdefault("file_sha256", {})
        if potcar:
            target = directory / "POTCAR"
            if target.exists() and sha256(target) != sha256(potcar):
                raise FileExistsError(f"different POTCAR already exists; refusing replacement: {target}")
            if not target.exists(): shutil.copy2(potcar, target)
            hashes["POTCAR"] = sha256(target)
            marker = directory / "POTCAR_REQUIRED"
            if marker.exists(): marker.unlink()
        if kpoints:
            target = directory / "KPOINTS"
            if target.exists() and sha256(target) != sha256(kpoints) and not replace_kpoints:
                raise FileExistsError(f"different KPOINTS exists; pass --replace-kpoints after review: {target}")
            shutil.copy2(kpoints, target); hashes["KPOINTS"] = sha256(target)
        record["ready_for_submission"] = all((directory / name).is_file() for name in ("POSCAR", "INCAR", "KPOINTS", "POTCAR", "job.slurm"))
        changed.append(record["id"])
    manifest.setdefault("hydration_history", []).append({"utc": utc_now(), "prior_manifest_sha256": before,
        "potcar_sha256": sha256(potcar) if potcar else None, "kpoints_sha256": sha256(kpoints) if kpoints else None,
        "replace_kpoints": replace_kpoints})
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    write_json(temporary, manifest); temporary.replace(manifest_path)
    return {"schema": "epirefine.hydrate.v1", "changed_runs": len(changed),
            "manifest": str(manifest_path.resolve()), "prior_manifest_sha256": before,
            "new_manifest_sha256": sha256(manifest_path)}


def audit_runs(manifest_path: Path, root: Path | None = None) -> dict[str, Any]:
    manifest = read_json(manifest_path); stage = manifest.get("stage")
    if stage not in {"relax", "static"}:
        raise ValueError("manifest stage must be relax or static")
    base = root or manifest_path.parent
    rows = []
    for record in manifest.get("runs", []):
        directory = resolve_run_directory(base, record["run_dir"])
        state, reason = "missing", "run directory absent or ambiguous"
        if directory:
            outcar, contcar = directory / "OUTCAR", directory / "CONTCAR"
            if not outcar.is_file():
                state, reason = ("queued", "job marker exists; OUTCAR absent") if (directory / ".epirefine-jobid").is_file() else ("not_started", "OUTCAR absent")
            elif stage == "relax":
                good, reason = relax_complete(outcar, contcar); state = "complete" if good else "incomplete"
            else:
                text = outcar.read_text(errors="replace")
                good = "General timing and accounting" in text and not FATAL.search(text) and bool(re.findall(rf"energy\(sigma->0\)\s*=\s*({FLOAT})", text))
                reason = "ok" if good else "normal static completion evidence absent"
                state = "complete" if good else "incomplete"
        rows.append({"id": record.get("id"), "plane": record.get("plane"), "run_dir": record.get("run_dir"),
                     "state": state, "reason": reason})
    counts = {state: sum(row["state"] == state for row in rows) for state in sorted({row["state"] for row in rows})}
    return {"schema": "epirefine.audit.v1", "created_utc": utc_now(), "stage": stage,
            "manifest": str(manifest_path.resolve()), "counts": counts, "rows": rows}


def submit_runs(manifest_path: Path, root: Path | None = None, execute: bool = False,
                limit: int | None = None) -> dict[str, Any]:
    validation = validate_scaffold(manifest_path, root)
    if validation["issues"]:
        raise ValueError("scaffold validation failed; run 'epirefine validate' and correct every issue")
    manifest = read_json(manifest_path); base = root or manifest_path.parent
    queued_by_directory: dict[str, str] = {}
    if execute:
        reply = subprocess.run(["squeue", "-u", os.environ.get("USER", ""), "-h", "-o", "%i|%Z"],
                               text=True, capture_output=True, check=True)
        for line in reply.stdout.splitlines():
            if "|" in line:
                job_id, workdir = line.split("|", 1)
                resolved = str(Path(workdir).resolve())
                if resolved in queued_by_directory:
                    raise RuntimeError(f"multiple queued jobs share working directory: {resolved}")
                queued_by_directory[resolved] = job_id
    rows = []
    submitted = 0
    for record in manifest.get("runs", []):
        directory = resolve_run_directory(base, record["run_dir"])
        marker = directory / ".epirefine-jobid"
        claim = directory / ".epirefine-submitting"
        existing_outputs = any((directory / name).exists() for name in ("OUTCAR", "OSZICAR", "vasp.out"))
        if marker.is_file():
            marker_value = marker.read_text().strip()
            if not marker_value.isdigit():
                raise ValueError(f"nonnumeric job marker requires manual repair: {marker}")
            rows.append({"id": record["id"], "action": "skip", "reason": "job marker exists",
                         "job_id": marker_value}); continue
        if existing_outputs:
            rows.append({"id": record["id"], "action": "skip", "reason": "output exists without job marker"}); continue
        queued = queued_by_directory.get(str(directory.resolve()))
        if queued:
            marker.write_text(queued + "\n")
            rows.append({"id": record["id"], "action": "reconciled", "job_id": queued}); continue
        if limit is not None and submitted >= limit:
            rows.append({"id": record["id"], "action": "skip", "reason": "submission limit"}); continue
        if not execute:
            rows.append({"id": record["id"], "action": "would_submit"}); submitted += 1; continue
        try:
            with claim.open("x") as handle:
                handle.write(utc_now() + "\n")
        except FileExistsError:
            rows.append({"id": record["id"], "action": "skip", "reason": "sticky submission claim; inspect scheduler history"}); continue
        try:
            reply = subprocess.run(["sbatch", "--parsable", "--chdir", str(directory), str(directory / "job.slurm")],
                                   text=True, capture_output=True, check=True)
            job_id = reply.stdout.strip().split(";", 1)[0]
            if not job_id.isdigit():
                raise RuntimeError(f"non-numeric sbatch reply: {reply.stdout!r}")
            marker.write_text(job_id + "\n"); claim.unlink(); submitted += 1
            rows.append({"id": record["id"], "action": "submitted", "job_id": job_id})
        except Exception:
            # Keep the claim: sbatch may have accepted the job before the client failed.
            raise
    return {"schema": "epirefine.submit.v1", "created_utc": utc_now(), "execute": execute,
            "submitted_or_planned": submitted, "rows": rows}


def collect_archive(root: Path, archive: Path, dry_run: bool = False) -> dict[str, Any]:
    root = root.resolve(); archive = archive.resolve()
    if not root.is_dir():
        raise ValueError(f"missing run root: {root}")
    if archive.exists():
        raise FileExistsError(f"refusing existing archive: {archive}")
    allowed = {"OUTCAR", "OSZICAR", "CONTCAR", "POSCAR", "INCAR", "KPOINTS", "job.slurm",
               "vasp.out", ".epirefine-jobid", "CHARGE.vasp", "SPIN.vasp",
               "SPIN_UP.vasp", "SPIN_DW.vasp"}
    files = sorted(path for path in root.rglob("*") if path.is_file() and
                   (path.name in allowed or path.suffix in {".json", ".csv"}
                    or (path.name.startswith("slurm-") and path.suffix in {".out", ".err"}))
                   and path.name != "POTCAR")
    report = {"schema": "epirefine.archive.v1", "created_utc": utc_now(), "source_root": str(root),
              "archive": str(archive), "file_count": len(files), "dry_run": dry_run,
              "files": [str(path.relative_to(root)) for path in files]}
    if dry_run:
        return report
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="epirefine-") as temporary:
        staging = Path(temporary); results = staging / "results"; metadata = staging / "metadata"
        results.mkdir(); metadata.mkdir()
        checksum_lines = []
        for source in files:
            relative = source.relative_to(root); destination = results / relative
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
            checksum_lines.append(f"{sha256(destination)}  results/{relative.as_posix()}\n")
        (metadata / "SHA256SUMS").write_text("".join(checksum_lines))
        write_json(metadata / "archive_manifest.json", report)
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(results, arcname="results"); tar.add(metadata, arcname="metadata")
    report["archive_sha256"] = sha256(archive)
    return report
