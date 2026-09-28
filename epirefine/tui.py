"""Optional terminal interface for common EpiRefine analysis and run operations.

The CLI remains the source of truth.  This module discovers project artifacts,
builds argument lists without a shell, and delegates every mutation to the same
``epirefine.cli`` entry point used by scripts.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .core import accepted_static, normalize_plane


REFERENCE = Path(__file__).resolve().parent / "data" / "CLI_REFERENCE.md"
SKIP_PARTS = {".git", ".venv", "__pycache__", "node_modules"}
TUI_COMMAND_COVERAGE = {
    "init": "Project setup", "propose": "Analysis/refinement", "scaffold-relax": "Scaffolding",
    "scaffold-direct-static": "Scaffolding", "scaffold-static": "Scaffolding",
    "ingest": "Analysis/refinement", "plot": "Analysis/refinement",
    "validate": "Run management", "hydrate": "Run management", "audit": "Run management",
    "submit": "Run management", "collect": "Run management", "tool-status": "External tools",
    "tool-config": "External tools", "extract-volumetric": "Volumetric analysis",
    "interface-match": "Heterostructure analysis", "hstruct": "Heterostructure analysis",
    "volume-slice": "Volumetric analysis", "help-all": "Built-in manual",
}


def _visible(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    return not any(part in SKIP_PARTS or part.startswith(".nox") for part in parts)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def summarize_history(path: Path) -> dict[str, Any]:
    """Return a dependency-free summary of a static-history CSV."""
    rows: list[dict[str, str]] = []
    try:
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return {"path": str(path), "readable": False, "rows": 0}
    accepted = [row for row in rows if accepted_static(row)]
    planes = Counter(normalize_plane(row.get("plane", "")) for row in accepted)
    iterations = Counter(row.get("source_iteration", "unknown") or "unknown" for row in accepted)
    moments: list[float] = []
    for row in accepted:
        for key in ("ru_mean_abs_muB", "mean_abs_muB", "magmom"):
            try:
                moments.append(float(row[key]))
                break
            except (KeyError, TypeError, ValueError):
                continue
    result: dict[str, Any] = {
        "path": str(path.resolve()), "readable": True, "rows": len(rows),
        "accepted_static_rows": len(accepted), "planes": dict(sorted(planes.items())),
        "iterations": dict(sorted(iterations.items())), "moment_values": len(moments),
    }
    if moments:
        result["moment_muB"] = {
            "min": min(moments), "max": max(moments), "mean": sum(moments) / len(moments),
        }
    return result


def summarize_manifest(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    runs = value.get("runs", []) if isinstance(value.get("runs", []), list) else []
    rejected = value.get("rejected_relaxations", [])
    planes = Counter(normalize_plane(str(row.get("plane", ""))) for row in runs if isinstance(row, dict))
    return {
        "path": str(path.resolve()), "schema": value.get("schema", "unknown"),
        "stage": value.get("stage", "unknown"), "runs": len(runs),
        "rejected": len(rejected) if isinstance(rejected, list) else 0,
        "planes": dict(sorted(planes.items())),
    }


def discover_project(root: Path) -> dict[str, Any]:
    """Discover useful EpiRefine artifacts without importing scientific packages."""
    root = root.expanduser().resolve()
    histories: list[Path] = []
    manifests: list[Path] = []
    audits: list[Path] = []
    if root.is_dir():
        for path in root.rglob("*"):
            if not path.is_file() or not _visible(path, root):
                continue
            if path.name.endswith("_manifest.json"):
                manifests.append(path)
            elif "audit" in path.name.lower() and path.suffix == ".json":
                audits.append(path)
            elif path.suffix == ".csv":
                try:
                    with path.open() as handle:
                        header = handle.readline().lower()
                except OSError:
                    continue
                if "plane" in header and ("eps_a" in header or "strain_a" in header):
                    histories.append(path)
    config = root / "config.json"
    config_value = _read_json(config) if config.is_file() else {}
    return {
        "schema": "epirefine.tui-snapshot.v1", "version": __version__, "root": str(root),
        "exists": root.is_dir(), "config": str(config) if config.is_file() else None,
        "system": config_value.get("system"), "configured_planes": config_value.get("planes", []),
        "command_coverage": TUI_COMMAND_COVERAGE,
        "histories": [summarize_history(path) for path in sorted(histories)],
        "manifests": [summarize_manifest(path) for path in sorted(manifests)],
        "audits": [str(path.resolve()) for path in sorted(audits)],
    }


def delegated_command(arguments: Sequence[str]) -> list[str]:
    """Build the exact no-shell command used by the TUI."""
    return [sys.executable, "-m", "epirefine.cli", *arguments]


class TerminalUI:
    def __init__(self, screen: Any, project: Path):
        self.screen = screen
        self.project = project.expanduser().resolve()
        self.status = "Ready"
        self._init_terminal()

    def _init_terminal(self) -> None:
        import curses
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.screen.keypad(True)
        if curses.has_colors():
            try:
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_CYAN, -1)
                curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
                curses.init_pair(3, curses.COLOR_YELLOW, -1)
            except curses.error:
                pass

    def _put(self, row: int, col: int, value: str, style: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if 0 <= row < height and col < width:
            try:
                self.screen.addnstr(row, col, value, max(0, width - col - 1), style)
            except Exception:
                pass

    def _header(self, title: str) -> int:
        import curses
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        bar = f" EpiRefine TUI {__version__} | {title} "
        self._put(0, 0, bar.ljust(max(1, width - 1)), curses.color_pair(2))
        self._put(1, 0, f"Project: {self.project}", curses.color_pair(1))
        self._put(height - 1, 0, self.status, curses.color_pair(3))
        return 3

    def menu(self, title: str, options: list[tuple[str, str]]) -> str | None:
        import curses
        selected = 0
        offset = 0
        while True:
            start = self._header(title)
            height, _ = self.screen.getmaxyx()
            room = max(1, height - start - 2)
            if selected < offset:
                offset = selected
            if selected >= offset + room:
                offset = selected - room + 1
            for visible, (key, label) in enumerate(options[offset:offset + room]):
                index = offset + visible
                prefix = "> " if index == selected else "  "
                style = curses.A_REVERSE if index == selected else 0
                self._put(start + visible, 1, prefix + label, style)
            self._put(height - 2, 0, "↑/↓ or j/k: move   Enter: select   q/Esc: back")
            self.screen.refresh()
            key = self.screen.getch()
            if key in (ord("q"), 27):
                return None
            if key in (curses.KEY_UP, ord("k")):
                selected = (selected - 1) % len(options)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = (selected + 1) % len(options)
            elif key in (10, 13, curses.KEY_ENTER):
                return options[selected][0]

    def prompt(self, label: str, default: str = "") -> str | None:
        import curses
        row = self._header("Input")
        self._put(row, 1, label)
        shown = f"[{default}] " if default else ""
        self._put(row + 2, 1, shown)
        self._put(row + 4, 1, "Enter accepts; blank uses the default; Esc is not captured while typing.")
        self.screen.refresh()
        curses.echo()
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        try:
            _, width = self.screen.getmaxyx()
            raw = self.screen.getstr(row + 2, 1 + len(shown), max(1, width - len(shown) - 4))
            value = raw.decode(errors="replace").strip()
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        return value or default

    def confirm_phrase(self, message: str, phrase: str) -> bool:
        value = self.prompt(f"{message} Type {phrase!r} to continue:")
        return value == phrase

    def show(self, title: str, content: str) -> None:
        import curses
        lines: list[str] = []
        _, width = self.screen.getmaxyx()
        for line in content.splitlines() or [""]:
            lines.extend(textwrap.wrap(line, width=max(20, width - 3), replace_whitespace=False,
                                       drop_whitespace=False) or [""])
        offset = 0
        while True:
            start = self._header(title)
            height, _ = self.screen.getmaxyx()
            room = max(1, height - start - 2)
            for index, line in enumerate(lines[offset:offset + room]):
                self._put(start + index, 1, line)
            self._put(height - 2, 0, "↑/↓, PgUp/PgDn: scroll   q/Esc/Enter: close")
            self.screen.refresh()
            key = self.screen.getch()
            if key in (ord("q"), 27, 10, 13, curses.KEY_ENTER):
                return
            if key in (curses.KEY_DOWN, ord("j")):
                offset = min(max(0, len(lines) - room), offset + 1)
            elif key in (curses.KEY_UP, ord("k")):
                offset = max(0, offset - 1)
            elif key == curses.KEY_NPAGE:
                offset = min(max(0, len(lines) - room), offset + room)
            elif key == curses.KEY_PPAGE:
                offset = max(0, offset - room)

    def run_cli(self, arguments: list[str], title: str) -> int:
        command = delegated_command(arguments)
        self.status = "Running: epirefine " + " ".join(arguments)
        self._header(title)
        self._put(4, 1, self.status)
        self.screen.refresh()
        working_directory = self.project if self.project.is_dir() else Path.cwd()
        reply = subprocess.run(command, cwd=working_directory, text=True,
                               capture_output=True, check=False)
        output = "$ " + " ".join(command) + "\n\n" + reply.stdout
        if reply.stderr:
            output += "\n[stderr]\n" + reply.stderr
        self.status = f"Finished with exit status {reply.returncode}"
        self.show(title, output)
        return reply.returncode

    def choose_path(self, title: str, records: list[dict[str, Any]]) -> Path | None:
        if not records:
            self.show(title, "No matching artifacts were found under the project root.")
            return None
        options = []
        for index, record in enumerate(records):
            path = Path(record["path"])
            try:
                label = str(path.relative_to(self.project))
            except ValueError:
                label = str(path)
            detail = f" ({record.get('stage', record.get('accepted_static_rows', '?'))})"
            options.append((str(index), label + detail))
        selected = self.menu(title, options)
        return Path(records[int(selected)]["path"]) if selected is not None else None

    def dashboard(self) -> dict[str, Any]:
        return discover_project(self.project)

    def yes_no(self, title: str, default: bool = False) -> bool | None:
        options = [("yes", "Yes"), ("no", "No")]
        if not default:
            options.reverse()
        value = self.menu(title, options)
        return None if value is None else value == "yes"

    def config_args(self) -> list[str]:
        config = self.project / "config.json"
        return ["--config", str(config)] if config.is_file() else []

    def choose_manifest(self, title: str, stage: str | None = None) -> Path | None:
        records = self.dashboard()["manifests"]
        if stage:
            records = [record for record in records if record.get("stage") == stage]
        return self.choose_path(title, records)

    def edit_file(self, path: Path) -> None:
        import curses
        editor = shlex.split(os.environ.get("EDITOR", "nano"))
        if not editor:
            self.show("Editor unavailable", "Set the EDITOR environment variable first.")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        curses.def_prog_mode()
        curses.endwin()
        try:
            reply = subprocess.run([*editor, str(path)], cwd=self.project if self.project.is_dir() else Path.cwd(),
                                   check=False)
            self.status = f"Editor exited with status {reply.returncode}"
        except FileNotFoundError:
            self.status = f"Editor not found: {editor[0]}"
        finally:
            try:
                curses.reset_prog_mode()
                self.screen.refresh()
            except curses.error:
                pass

    def project_setup(self) -> None:
        action = self.menu("Project setup and editable inputs", [
            ("init", "Initialize this project directory"),
            ("ensure", "Add missing standard folders/templates without overwriting"),
            ("layout", "Show where structures, results, and templates belong"),
            ("edit", "Edit config.json or a project template with $EDITOR"),
        ])
        if action == "init":
            if self.project.is_dir() and any(self.project.iterdir()):
                self.show("Initialize project", "The selected project directory is non-empty. "
                          "EpiRefine refuses to overwrite it; choose a new --project path.")
                return
            system = self.prompt("System label", self.project.name)
            arguments = ["init", str(self.project)]
            if system:
                arguments += ["--system", system]
            self.run_cli(arguments, "Initialize project")
        elif action == "ensure":
            system = self.prompt("System label, used only if config.json is missing", self.project.name)
            arguments = ["init", str(self.project), "--ensure-layout"]
            if system: arguments += ["--system", system]
            self.run_cli(arguments, "Ensure project layout")
        elif action == "layout":
            layout = self.project / "PROJECT_LAYOUT.md"
            packaged = Path(__file__).resolve().parent / "data" / "PROJECT_LAYOUT.md"
            self.show("Project layout", (layout if layout.is_file() else packaged).read_text())
        elif action == "edit":
            paths = [self.project / "config.json"]
            template_directory = self.project / "templates"
            if template_directory.is_dir():
                paths.extend(sorted(path for path in template_directory.iterdir() if path.is_file()))
            existing = [path for path in paths if path.is_file()]
            if not existing:
                self.show("Edit project", "Initialize the project first; no editable files were found.")
                return
            choice = self.menu("Select file to edit", [(str(index), str(path.relative_to(self.project)))
                                                        for index, path in enumerate(existing)])
            if choice is not None:
                self.edit_file(existing[int(choice)])

    def history_analysis(self) -> None:
        path = self.choose_path("Select static history", self.dashboard()["histories"])
        if path:
            self.show("Static history analysis", json.dumps(summarize_history(path), indent=2, sort_keys=True))

    def plot(self) -> None:
        history = self.choose_path("Select history to plot", self.dashboard()["histories"])
        if not history:
            return
        output = self.prompt("Output directory", str(self.project / "plots" / "tui"))
        planes = self.prompt("Optional ordered planes, separated by spaces", "")
        markers = self.prompt("Optional marker CSV", "")
        arguments = ["plot", "--input", str(history), "--out", output]
        if planes:
            arguments += ["--planes", *planes.split()]
        if markers:
            arguments += ["--markers", markers]
        self.run_cli(arguments, "Plot contours")

    def propose(self) -> None:
        history = self.choose_path("Select accepted static history", self.dashboard()["histories"])
        if not history:
            return
        iteration = self.prompt("Iteration label", "next")
        output = self.prompt("Proposal CSV", str(self.project / "iterations" / iteration / "proposed_points.csv"))
        budget = self.prompt("Optional point budget", "")
        arguments = ["propose", "--input", str(history), "--out", output,
                     "--iteration", iteration, *self.config_args()]
        if budget:
            arguments += ["--budget", budget]
        self.run_cli(arguments, "Adaptive proposal")

    def ingest(self) -> None:
        manifest = self.choose_manifest("Select static manifest", "static")
        if not manifest:
            return
        results = self.prompt("Static results root", str(manifest.parent))
        histories = self.dashboard()["histories"]
        history_default = histories[-1]["path"] if histories else ""
        history = self.prompt("Existing history to extend (blank starts one)", history_default)
        output = self.prompt("New immutable history CSV",
                             str(self.project / "data" / "processed" / "static_history_next.csv"))
        arguments = ["ingest", "--results", results, "--manifest", str(manifest),
                     "--out", output, *self.config_args()]
        if history:
            arguments += ["--history", history]
        self.run_cli(arguments, "Ingest static results")

    def analysis_menu(self) -> None:
        action = self.menu("Data analysis and adaptive refinement", [
            ("history", "Summarize accepted static history"),
            ("plot", "Plot contours and sampling history"),
            ("propose", "Propose the next adaptive iteration"),
            ("ingest", "Ingest completed static OUTCARs"),
        ])
        if action == "history": self.history_analysis()
        elif action == "plot": self.plot()
        elif action == "propose": self.propose()
        elif action == "ingest": self.ingest()

    def scaffold_from_points(self, command: str, title: str, output_name: str) -> None:
        proposals = sorted(self.project.rglob("proposed_points.csv")) if self.project.is_dir() else []
        default_points = str(proposals[-1]) if proposals else str(self.project / "iterations" / "next" / "proposed_points.csv")
        points = self.prompt("Proposal CSV", default_points)
        history = self.choose_path("Select accepted static history", self.dashboard()["histories"])
        if not history:
            return
        source = self.prompt("Accepted geometry source root",
                             str(self.project / "data" / "raw" / "accepted_geometries"))
        output = self.prompt(f"New {title.lower()} directory",
                             str(self.project / "iterations" / "next" / output_name))
        potcar = self.prompt("Optional secure POTCAR path (prefer HPC hydrate)", "")
        kpoints = self.prompt("Optional converged KPOINTS path", "")
        dry = self.yes_no("Create a manifest-only dry-run preview?", True)
        if dry is None:
            return
        arguments = [command, "--points", points, "--history", str(history),
                     "--source-root", source, "--out", output, *self.config_args()]
        if potcar: arguments += ["--potcar", potcar]
        if kpoints: arguments += ["--kpoints", kpoints]
        if dry: arguments.append("--dry-run")
        self.run_cli(arguments, title)

    def scaffold_relax(self) -> None:
        self.scaffold_from_points("scaffold-relax", "Scaffold relaxations", "relax")

    def scaffold_direct_static(self) -> None:
        self.scaffold_from_points("scaffold-direct-static", "Scaffold direct statics", "static_direct")

    def scaffold_static(self, manifest: Path | None = None) -> None:
        manifest = manifest or self.choose_manifest("Select relaxation manifest", "relax")
        if not manifest:
            return
        results = self.prompt("Relaxation results root", str(manifest.parent))
        output = self.prompt("New static scaffold directory", str(manifest.parent.parent / "static"))
        potcar = self.prompt("Optional secure POTCAR path (prefer HPC hydrate)", "")
        kpoints = self.prompt("Optional converged KPOINTS path", "")
        dry = self.yes_no("Create a decision-only dry-run preview?", True)
        if dry is None:
            return
        arguments = ["scaffold-static", "--relax-manifest", str(manifest),
                     "--relax-results", results, "--out", output, *self.config_args()]
        if potcar: arguments += ["--potcar", potcar]
        if kpoints: arguments += ["--kpoints", kpoints]
        if dry: arguments.append("--dry-run")
        self.run_cli(arguments, "Scaffold statics")

    def scaffold_menu(self) -> None:
        action = self.menu("Calculation scaffolding", [
            ("relax", "Scaffold relaxation inputs"),
            ("direct", "Scaffold direct statics without ionic relaxation"),
            ("static", "Scaffold statics from completed relaxations"),
        ])
        if action == "relax": self.scaffold_relax()
        elif action == "direct": self.scaffold_direct_static()
        elif action == "static": self.scaffold_static()

    def hydrate(self, manifest: Path) -> None:
        root = self.prompt("Optional moved scaffold root", "")
        potcar = self.prompt("Secure POTCAR path", "")
        kpoints = self.prompt("Optional converged KPOINTS path", "")
        if not potcar and not kpoints:
            self.show("Hydrate", "At least one POTCAR or KPOINTS path is required.")
            return
        arguments = ["hydrate", "--manifest", str(manifest)]
        if root: arguments += ["--root", root]
        if potcar: arguments += ["--potcar", potcar]
        if kpoints:
            arguments += ["--kpoints", kpoints]
            if self.yes_no("Replace existing KPOINTS files?", False):
                arguments.append("--replace-kpoints")
        self.run_cli(arguments, "Hydrate scaffold")

    def collect(self, default_root: Path, stage: str) -> None:
        root = self.prompt("Run root to archive", str(default_root))
        archive = self.prompt("New archive path", str(self.project / f"{stage}_results.tar.gz"))
        mode = self.menu("Collection mode", [("preview", "Dry-run file/extraction preview"),
                                              ("collect", "Create checksummed archive")])
        if mode is None:
            return
        arguments = ["collect", "--root", root, "--archive", archive]
        if mode == "preview": arguments.append("--dry-run")
        use_vaspkit = self.yes_no("Extract viewer-ready volumes with VASPKIT first?", False)
        if use_vaspkit:
            products = self.prompt("Products: charge spin spin-components", "charge spin").split()
            arguments += ["--vaspkit-extract", *products]
            registry = self.prompt("Optional tool registry", "")
            timeout = self.prompt("Optional per-task timeout in seconds", "")
            if registry: arguments += ["--tool-registry", registry]
            if timeout: arguments += ["--vaspkit-timeout", timeout]
            if self.yes_no("Allow replacement of existing VASPKIT outputs?", False):
                arguments.append("--vaspkit-replace")
            if mode != "preview" and not self.confirm_phrase("Run bulk VASPKIT extraction?", "EXTRACT"):
                self.status = "Collection cancelled"
                return
        self.run_cli(arguments, "Collect results")

    def manage_manifest(self) -> None:
        manifest = self.choose_manifest("Select run manifest")
        if not manifest:
            return
        summary = summarize_manifest(manifest)
        stage = summary["stage"]
        action = self.menu(f"Manage {manifest.name}", [
            ("inspect", "Inspect manifest summary"), ("hydrate", "Hydrate POTCAR/KPOINTS"),
            ("validate", "Validate scaffold and hashes"), ("audit", "Audit run completion"),
            ("preview", "Preview duplicate-safe submission"),
            ("submit", "SUBMIT eligible jobs (typed confirmation)"),
            ("static", "Scaffold statics (relax manifests only)"),
            ("collect", "Preview or create results archive"),
        ])
        root = ""
        if action in {"validate", "audit", "preview", "submit"}:
            root = self.prompt("Optional moved scaffold root", "")
        if action == "inspect":
            self.show("Manifest summary", json.dumps(summary, indent=2, sort_keys=True))
        elif action == "hydrate": self.hydrate(manifest)
        elif action == "validate":
            arguments = ["validate", "--manifest", str(manifest)]
            if root: arguments += ["--root", root]
            self.run_cli(arguments, "Validate scaffold")
        elif action == "audit":
            output = self.prompt("Audit JSON", str(manifest.parent / f"{stage}_audit_tui.json"))
            arguments = ["audit", "--manifest", str(manifest), "--out", output]
            if root: arguments += ["--root", root]
            self.run_cli(arguments, "Audit runs")
        elif action in {"preview", "submit"}:
            limit = self.prompt("Optional submission limit", "")
            arguments = ["submit", "--manifest", str(manifest)]
            if root: arguments += ["--root", root]
            if limit: arguments += ["--limit", limit]
            if action == "submit":
                if not self.confirm_phrase(f"Submit eligible runs in {manifest}?", "SUBMIT"):
                    self.status = "Submission cancelled"; return
                arguments.append("--execute")
            self.run_cli(arguments, "Submit runs" if action == "submit" else "Submission preview")
        elif action == "static":
            if stage != "relax":
                self.show("Scaffold statics", "This action requires a relaxation manifest.")
            else:
                self.scaffold_static(manifest)
        elif action == "collect": self.collect(manifest.parent, stage)

    def tools(self) -> None:
        action = self.menu("External tools", [("status", "Show/save companion-tool status"),
                                               ("vaspkit", "Register a VASPKIT executable")])
        registry = self.prompt("Optional nondefault tool registry", "") if action else ""
        if action == "status":
            output = self.prompt("Optional status JSON", "")
            arguments = ["tool-status"]
            if registry: arguments += ["--tool-registry", registry]
            if output: arguments += ["--out", output]
            self.run_cli(arguments, "External tool status")
        elif action == "vaspkit":
            path = self.prompt("Absolute path to independently acquired VASPKIT")
            if path:
                arguments = ["tool-config", "vaspkit", "--path", path]
                if registry: arguments += ["--tool-registry", registry]
                self.run_cli(arguments, "Configure VASPKIT")

    def vaspkit(self) -> None:
        root = self.prompt("Root containing CHGCAR run directories", str(self.project))
        products = self.prompt("Products: charge spin spin-components", "charge spin").split()
        registry = self.prompt("Optional tool registry", "")
        timeout = self.prompt("Optional per-task timeout in seconds", "")
        output = self.prompt("Optional report JSON", "")
        mode = self.menu("Extraction mode", [("preview", "Dry-run preview"), ("run", "Run extraction")])
        if mode is None:
            return
        arguments = ["extract-volumetric", "--root", root, "--products", *products]
        if registry: arguments += ["--tool-registry", registry]
        if timeout: arguments += ["--timeout", timeout]
        if output: arguments += ["--out", output]
        if self.yes_no("Allow replacement of existing derived volumes?", False):
            arguments.append("--replace")
        if mode == "preview": arguments.append("--dry-run")
        elif not self.confirm_phrase("Run VASPKIT throughout this tree?", "EXTRACT"):
            self.status = "Extraction cancelled"; return
        self.run_cli(arguments, "VASPKIT volumetric extraction")

    def volume_slice(self) -> None:
        volume = self.prompt("CHARGE.vasp, SPIN.vasp, CHGCAR, LOCPOT, or other volume")
        if not volume:
            return
        output = self.prompt("Output PNG", str(self.project / "plots" / "volume_slice.png"))
        dataset = self.prompt("Volumetric dataset index", "0")
        center = self.prompt("Central atom label", "Ru2")
        poly = self.prompt("Polyhedron atom labels", "O2 O5 O8 O9 O11 O12").split()
        plane = self.prompt("Exactly three plane atom labels", "Ru2 O2 O5").split()
        if len(plane) != 3:
            self.show("Invalid input", "Exactly three plane atom labels are required."); return
        isolevels = self.prompt("Optional numeric isolevels separated by spaces", "")
        grid = self.prompt("Grid points", "260")
        padding = self.prompt("Padding in Angstrom", "0.8")
        span = self.prompt("Optional square span in Angstrom", "")
        cmap = self.prompt("Matplotlib colormap", "RdBu_r")
        transform = self.prompt("Value transform: raw, logabs, or signed-log", "raw")
        log_floor = self.prompt("Log floor", "1e-4")
        tolerance = self.prompt("Atom-plane tolerance", "0.15")
        title = self.prompt("Optional figure title", "")
        report = self.prompt("Provenance report JSON", str(Path(output).with_suffix(".json")))
        mode = self.menu("Slice mode", [("preview", "Dry-run command preview"), ("render", "Render now")])
        if mode is None: return
        arguments = ["volume-slice", "--volume", volume, "--output", output, "--dataset", dataset,
                     "--center", center, "--poly-atoms", *poly, "--plane-atoms", *plane,
                     "--grid-points", grid, "--padding", padding, "--cmap", cmap,
                     "--value-transform", transform, "--log-floor", log_floor,
                     "--atom-plane-tolerance", tolerance]
        if isolevels: arguments += ["--isolevels", *isolevels.split()]
        if span: arguments += ["--span", span]
        if title: arguments += ["--title", title]
        if report: arguments += ["--report", report]
        if self.yes_no("Disable symmetric color limits?", False): arguments.append("--no-symmetric-color")
        if mode == "preview": arguments.append("--dry-run")
        self.run_cli(arguments, "Volumetric slice")

    def interface_match(self) -> None:
        structures = self.project / "inputs" / "structures"
        substrate = self.prompt("Substrate POSCAR/CIF", str(structures / "substrate.vasp"))
        film = self.prompt("Film POSCAR/CIF", str(structures / "film.vasp"))
        if not substrate or not film: return
        substrate_plane = self.prompt("Substrate plane; blank uses input a/b", "")
        film_plane = self.prompt("Film plane; blank uses input a/b", "")
        substrate_layers = self.prompt("Substrate surface layers", "1")
        film_layers = self.prompt("Film surface layers", "1")
        substrate_repeats = self.prompt("Substrate repeats A B", "1 1").split()
        film_repeats = self.prompt("Film repeats A B", "1 1").split()
        if len(substrate_repeats) != 2 or len(film_repeats) != 2:
            self.show("Invalid repeats", "Each repeat field requires exactly two integers."); return
        output = self.prompt("JSON report", str(self.project / "provenance" / "interface_match.json"))
        arguments = ["interface-match", substrate, film, "--out", output,
                     "--substrate-layers", substrate_layers, "--film-layers", film_layers,
                     "--substrate-repeats", *substrate_repeats, "--film-repeats", *film_repeats]
        if substrate_plane: arguments += ["--substrate-plane", substrate_plane]
        if film_plane: arguments += ["--film-plane", film_plane]
        if self.yes_no("Swap substrate in-plane axes?", False): arguments.append("--substrate-swap-axes")
        if self.yes_no("Swap film in-plane axes?", False): arguments.append("--film-swap-axes")
        marker = self.prompt("Optional contour marker CSV", "")
        if marker:
            marker_plane = self.prompt("Contour plane label")
            marker_label = self.prompt("Marker label")
            arguments += ["--marker-out", marker, "--marker-plane", marker_plane,
                          "--marker-label", marker_label]
        self.run_cli(arguments, "Interface mismatch")

    def hstruct(self) -> None:
        raw = self.prompt("hstructpy arguments (for example: domain-search substrate film --json)")
        if raw:
            try: arguments = shlex.split(raw)
            except ValueError as error:
                self.show("Invalid arguments", str(error)); return
            self.run_cli(["hstruct", "--", *arguments], "hstructpy passthrough")

    def heterostructure_menu(self) -> None:
        action = self.menu("Heterostructure analysis", [
            ("match", "Typed interface mismatch and contour marker"),
            ("hstruct", "Complete hstructpy passthrough (build/batch/domain/GUI)"),
        ])
        if action == "match": self.interface_match()
        elif action == "hstruct": self.hstruct()

    def volumetric_menu(self) -> None:
        action = self.menu("Volumetric analysis", [("vaspkit", "Bulk VASPKIT extraction"),
                                                    ("slice", "Render/preview planar volume slice")])
        if action == "vaspkit": self.vaspkit()
        elif action == "slice": self.volume_slice()

    def arbitrary_cli(self) -> None:
        raw = self.prompt("Arguments after 'epirefine' (no shell operators)")
        if not raw: return
        try: arguments = shlex.split(raw)
        except ValueError as error:
            self.show("Invalid arguments", str(error)); return
        if not arguments: return
        if arguments[0] == "submit" and "--execute" in arguments:
            if not self.confirm_phrase("The command requests real Slurm submission.", "SUBMIT"): return
        if arguments[0] == "extract-volumetric" and "--dry-run" not in arguments:
            if not self.confirm_phrase("The command requests real bulk extraction.", "EXTRACT"): return
        self.run_cli(arguments, "Advanced CLI console")

    def loop(self) -> None:
        while True:
            choice = self.menu("Main menu", [
                ("dashboard", "Project dashboard"),
                ("setup", "Project setup, input layout, config, and templates"),
                ("analysis", "History analysis, plot, propose, and ingest"),
                ("scaffold", "Scaffold relaxations or statics"),
                ("runs", "Hydrate, validate, audit, submit, and collect runs"),
                ("tools", "Inspect or configure optional external tools"),
                ("hetero", "Interface matching and complete hstructpy tools"),
                ("volume", "VASPKIT extraction and volumetric slices"),
                ("advanced", "Advanced arbitrary CLI arguments (no shell)"),
                ("manual", "Read the complete CLI manual"),
            ])
            if choice is None: return
            if choice == "dashboard": self.show("Project dashboard", json.dumps(self.dashboard(), indent=2, sort_keys=True))
            elif choice == "setup": self.project_setup()
            elif choice == "analysis": self.analysis_menu()
            elif choice == "scaffold": self.scaffold_menu()
            elif choice == "runs": self.manage_manifest()
            elif choice == "tools": self.tools()
            elif choice == "hetero": self.heterostructure_menu()
            elif choice == "volume": self.volumetric_menu()
            elif choice == "advanced": self.arbitrary_cli()
            elif choice == "manual": self.show("CLI manual", REFERENCE.read_text())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epirefine-tui",
        description="Optional terminal interface for common EpiRefine analysis and run operations.",
        epilog="The epirefine CLI remains fully usable without this interface.",
    )
    parser.add_argument("--project", type=Path, default=Path.cwd(),
                        help="project directory to discover (default: current directory)")
    parser.add_argument("--snapshot", action="store_true",
                        help="print the discovered project dashboard as JSON without opening curses")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    project = args.project.expanduser().resolve()
    if args.snapshot:
        print(json.dumps(discover_project(project), indent=2, sort_keys=True))
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("epirefine-tui: an interactive terminal is required; use --snapshot for noninteractive inspection",
              file=sys.stderr)
        return 2
    try:
        import curses
        curses.wrapper(lambda screen: TerminalUI(screen, project).loop())
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
