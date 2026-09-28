from __future__ import annotations

import csv
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

from epirefine.api import (VaspkitExtractionRequest, VolumeSliceRequest,
                           configure_external_tool, extract_vaspkit_volumes,
                           marker_from_match, render_volume_slice, tool_status)
from epirefine.cli import CLI_REFERENCE, DEFAULT_CONFIG, PACKAGE_ROOT, main, parser
from epirefine.core import (collect_archive, ingest, parse_poscar, propose,
                            scaffold_direct_static, scaffold_relax, scaffold_static,
                            submit_runs, validate_scaffold)
from epirefine.tui import (TUI_COMMAND_COVERAGE, delegated_command, discover_project,
                           main as tui_main, summarize_history)


POSCAR = """synthetic RuO2
1.0
2 0 0
0 3 0
0 0 4
Ru O
4 8
Direct
0 0 0
0.5 0.5 0.5
0.25 0.25 0.25
0.75 0.75 0.75
0 0 0.25
0 0 0.75
0.5 0 0.25
0.5 0 0.75
0 0.5 0.25
0 0.5 0.75
0.5 0.5 0.25
0.5 0.5 0.75
"""


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def outcar(relax: bool) -> str:
    accuracy = "reached required accuracy - stopping structural energy minimisation\n" if relax else ""
    rows = "\n".join(f" {index:3d}  0.000  0.000  0.000  {(-1) ** index * (0.2 if index <= 4 else 0.01):.6f}" for index in range(1, 13))
    return (accuracy + "magnetization (x)\n # of ion       s       p       d       tot\n -----\n" + rows +
            "\n tot 0 0 0 0\n energy(sigma->0) = -12.345\n General timing and accounting informations for this job:\n")


class WorkflowTest(unittest.TestCase):
    def test_init_creates_documented_input_and_template_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "new-project"
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["init", str(project), "--system", "test-system"]), 0)
            for relative in ("inputs/structures", "inputs/kpoints", "inputs/markers",
                             "data/raw/accepted_geometries", "data/raw/transfers",
                             "data/processed", "templates"):
                self.assertTrue((project / relative).is_dir(), relative)
            for name in ("relax.INCAR", "static.INCAR", "relax.job.slurm",
                         "static.job.slurm", "KPOINTS"):
                self.assertTrue((project / "templates" / name).is_file(), name)
            self.assertTrue((project / "PROJECT_LAYOUT.md").is_file())
            custom = project / "templates" / "relax.INCAR"
            custom.write_text("USER CUSTOM TEMPLATE\n")
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["init", str(project), "--ensure-layout"]), 0)
            self.assertEqual(custom.read_text(), "USER CUSTOM TEMPLATE\n")

    def test_tui_snapshot_and_project_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config.json").write_text(json.dumps({"system": "RuO2", "planes": ["001"]}))
            history = root / "static_history.csv"
            write_csv(history, [{"plane": "001", "eps_a_percent": 0, "eps_b_percent": 0,
                                 "ru_mean_abs_muB": 0.25, "parse_status": "ok",
                                 "source_type": "static", "source_iteration": "initial"}])
            manifest = root / "relax_manifest.json"
            manifest.write_text(json.dumps({"schema": "epirefine.scaffold.v1", "stage": "relax",
                                             "runs": [{"plane": "001"}]}))
            snapshot = discover_project(root)
            self.assertEqual(snapshot["system"], "RuO2")
            self.assertEqual(snapshot["histories"][0]["accepted_static_rows"], 1)
            self.assertEqual(snapshot["manifests"][0]["stage"], "relax")
            self.assertAlmostEqual(summarize_history(history)["moment_muB"]["mean"], 0.25)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(tui_main(["--project", str(root), "--snapshot"]), 0)
            self.assertEqual(json.loads(output.getvalue())["root"], str(root.resolve()))
            command = delegated_command(["audit", "--manifest", str(manifest)])
            self.assertEqual(command[1:3], ["-m", "epirefine.cli"])
            self.assertNotIn("shell=True", command)

    def test_every_command_help_and_comprehensive_reference(self) -> None:
        commands = tuple(parser()._subparsers._group_actions[0].choices)
        self.assertEqual(set(commands), set(TUI_COMMAND_COVERAGE))
        self.assertTrue(CLI_REFERENCE.is_file())
        reference = CLI_REFERENCE.read_text()
        for command in commands:
            with self.subTest(command=command), self.assertRaises(SystemExit) as stopped:
                with redirect_stdout(StringIO()):
                    parser().parse_args([command, "--help"])
            self.assertEqual(stopped.exception.code, 0)
            self.assertIn(f"## `{command}`", reference)
            self.assertGreaterEqual(reference.split(f"## `{command}`", 1)[1].split("\n## `", 1)[0].count("```bash"), 3)
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["help-all"]), 0)
        self.assertEqual(output.getvalue(), reference)

    def test_companion_api_discovery_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hstruct = root / "hstructpy"
            module = hstruct / "src" / "hstructpy"
            module.mkdir(parents=True)
            (module / "__init__.py").write_text('__version__ = "9.8.7"\n')
            slice_script = root / "plot_polyhedron_slice.py"
            slice_script.write_text("# fixture backend\n")
            environment = {
                "HSTRUCTPY_ROOT": str(hstruct),
                "POLYHEDRON_SLICE_ROOT": str(slice_script),
            }
            with patch.dict("os.environ", environment, clear=False):
                status = tool_status()
                self.assertTrue(status["hstructpy"]["available"])
                self.assertEqual(status["hstructpy"]["version"], "9.8.7")
                self.assertTrue(status["volume_slice"]["available"])
                report = render_volume_slice(VolumeSliceRequest(
                    volume=root / "SPIN.vasp", output=root / "slice.png",
                    plane_atoms=("Ru1", "O1", "O2"), isolevels=(-0.1, 0.0, 0.1),
                ), dry_run=True)
            self.assertTrue(report["dry_run"])
            self.assertIn("-0.1,0.0,0.1", report["command"])
            self.assertFalse((root / "slice.png").exists())

            marker = marker_from_match(
                {"mismatch_a_percent": -4.7, "mismatch_b_percent": 2.3},
                "(110)", "TiO2(110)",
            )
            self.assertEqual(marker["plane"], "110")
            self.assertEqual(marker["eps_a_percent"], -4.7)

    def test_vaspkit_registry_bulk_extraction_and_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "vaspkit"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\nimport sys\n"
                "task=sys.stdin.readline().strip()\n"
                "names={'311':['CHARGE.vasp'],'312':['SPIN.vasp'],"
                "'313':['SPIN_UP.vasp','SPIN_DW.vasp']}[task]\n"
                "[Path(name).write_text(task+' volume\\n') for name in names]\n"
            )
            executable.chmod(0o755)
            registry = root / "tools.json"
            configured = configure_external_tool("vaspkit", executable, registry)
            self.assertEqual(configured["tool"], "vaspkit")
            run = root / "runs" / "001" / "point"; run.mkdir(parents=True)
            (run / "CHGCAR").write_text("fixture\n")
            report = extract_vaspkit_volumes(VaspkitExtractionRequest(
                root=root / "runs", products=("charge", "spin", "spin-components"),
                registry=registry,
            ))
            self.assertEqual(report["counts"]["extracted"], 3)
            for name in ("CHARGE.vasp", "SPIN.vasp", "SPIN_UP.vasp", "SPIN_DW.vasp"):
                self.assertTrue((run / name).is_file())
            archive = root / "volumes.tar.gz"
            collection = collect_archive(root / "runs", archive)
            with tarfile.open(archive) as handle:
                names = handle.getnames()
            self.assertTrue(any(name.endswith("SPIN.vasp") for name in names))
            self.assertTrue(any(name.endswith(".epirefine-vaspkit.json") for name in names))

    def test_end_to_end_and_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "source"; source.mkdir()
            (source / "CONTCAR").write_text(POSCAR); (source / "POTCAR").write_text("licensed-test-placeholder\n")
            (source / "KPOINTS").write_text("mesh\n0\nGamma\n2 2 2\n0 0 0\n")
            history = root / "history.csv"
            rows = []
            for x, y, moment in [(-1, -1, 0.0), (1, -1, 0.3), (-1, 1, 0.0), (1, 1, 0.3)]:
                rows.append({"plane": "001", "eps_a_percent": x, "eps_b_percent": y,
                             "ru_mean_abs_muB": moment, "parse_status": "ok", "source_type": "coarse_static",
                             "relax_contcar": str(source / "CONTCAR"), "run_dir": f"old_{x}_{y}",
                             "source_iteration": "initial"})
            write_csv(history, rows)
            settings = dict(DEFAULT_CONFIG); settings.update({"budget": 2, "iteration": "iter01",
                "strain_bounds_percent": [-2, 2], "max_unresolved_diameter_percent": .5,
                "boundary_spacing_percent": .05})
            proposals = root / "proposals.csv"
            report = propose(history, proposals, settings)
            self.assertGreater(report["proposed_points"], 0)

            direct = root / "direct-static"
            direct_manifest = scaffold_direct_static(
                proposals, history, root, direct, PACKAGE_ROOT, "test",
                source / "POTCAR", source / "KPOINTS", "vasp_std",
            )
            self.assertEqual(direct_manifest["stage"], "static")
            self.assertEqual(direct_manifest["construction_mode"], "direct_static")
            self.assertTrue(validate_scaffold(direct / "static_manifest.json")["valid"])
            for record in direct_manifest["runs"]:
                self.assertFalse(record["ionic_relaxation_performed"])
                directory = direct / record["run_dir"]
                self.assertIn("NSW = 0", (directory / "INCAR").read_text())
                (directory / "OUTCAR").write_text(outcar(relax=False))
            direct_summary = root / "direct_summary.csv"
            direct_report = ingest(direct, direct / "static_manifest.json", direct_summary, ["Ru"])
            self.assertEqual(direct_report["incoming_ok"], len(direct_manifest["runs"]))
            with direct_summary.open() as handle:
                direct_rows = list(csv.DictReader(handle))
            metadata = json.loads(direct_rows[0]["sample_metadata_json"])
            self.assertEqual(metadata["geometry_protocol"], "direct_static")
            self.assertFalse(metadata["relaxed_at_target"])
            self.assertEqual(direct_rows[0]["geometry_protocol"], "direct_static")

            relax = root / "relax"
            manifest = scaffold_relax(proposals, history, root, relax, PACKAGE_ROOT, "test",
                                      source / "POTCAR", source / "KPOINTS", "vasp_std")
            self.assertTrue(validate_scaffold(relax / "relax_manifest.json")["valid"])
            self.assertEqual(submit_runs(relax / "relax_manifest.json")["submitted_or_planned"], len(manifest["runs"]))
            first = relax / manifest["runs"][0]["run_dir"]
            parsed = parse_poscar(first / "POSCAR")
            self.assertNotAlmostEqual(parsed["cell"][0][0], 2.0)
            for record in manifest["runs"]:
                directory = relax / record["run_dir"]
                (directory / "CONTCAR").write_text((directory / "POSCAR").read_text())
                (directory / "OUTCAR").write_text(outcar(relax=True))

            static = root / "static"
            static_manifest = scaffold_static(relax / "relax_manifest.json", relax, static, PACKAGE_ROOT,
                                              "test", source / "POTCAR", source / "KPOINTS", "vasp_std")
            self.assertEqual(len(static_manifest["rejected_relaxations"]), 0)
            self.assertTrue(validate_scaffold(static / "static_manifest.json")["valid"])
            for record in static_manifest["runs"]:
                directory = static / record["run_dir"]
                (directory / "OUTCAR").write_text(outcar(relax=False))

            summary = root / "summary.csv"
            ingest_report = ingest(static, static / "static_manifest.json", summary, ["Ru"])
            self.assertEqual(ingest_report["incoming_ok"], len(static_manifest["runs"]))
            with summary.open() as handle:
                for row in csv.DictReader(handle):
                    self.assertEqual(row["calculation_stage"], "static")
                    self.assertEqual(row["geometry_protocol"], "relaxed_static")
                    self.assertAlmostEqual(float(row["ru_mean_abs_muB"]), 0.2)
                    self.assertTrue(Path(row["geometry_path"]).is_file())

            archive = root / "transfer.tar.gz"
            collection = collect_archive(static, archive)
            self.assertGreater(collection["file_count"], 0)
            with tarfile.open(archive) as handle:
                names = handle.getnames()
            self.assertTrue(any(name.endswith("metadata/SHA256SUMS") for name in names))
            self.assertFalse(any(name.endswith("POTCAR") for name in names))

    def test_static_handoff_rejects_unconverged_relax(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); run = root / "relax" / "001" / "p1"; run.mkdir(parents=True)
            (run / "CONTCAR").write_text(POSCAR); (run / "OUTCAR").write_text("General timing and accounting\n")
            manifest = {"stage": "relax", "runs": [{"id": "p1", "plane": "001", "eps_a_percent": 0,
                        "eps_b_percent": 0, "run_dir": "001/p1"}]}
            path = root / "relax" / "relax_manifest.json"; path.write_text(json.dumps(manifest))
            result = scaffold_static(path, root / "relax", root / "static", PACKAGE_ROOT, "test", None, None, "vasp_std")
            self.assertEqual(len(result["runs"]), 0)
            self.assertEqual(len(result["rejected_relaxations"]), 1)


if __name__ == "__main__":
    unittest.main()
