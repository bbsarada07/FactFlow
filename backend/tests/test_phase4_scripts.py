"""Phase 4 scripts (review fixes, docs/REVIEW_PHASE4_5.md): one copy in backend/scripts, paths inside backend,
and the benchmark generator never overwrites a teammate's files or manifest rows. Each test failed before its fix."""
import csv
import importlib.util
import subprocess
import sys

from config import BASE_DIR

REPO = BASE_DIR.parent
BENCH = BASE_DIR / "data" / "benchmark"
PHASE4_SCRIPTS = ("measure_attacks.py", "record_demo_run.py", "generate_benchmark_cases.py")


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"_review_{name[:-3]}", BASE_DIR / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase4_scripts_live_only_in_backend_scripts():
    for name in PHASE4_SCRIPTS:
        assert (BASE_DIR / "scripts" / name).is_file()
        assert not (REPO / "scripts" / name).exists()


def test_phase4_scripts_resolve_their_paths_inside_backend():
    measure = _load_script("measure_attacks.py")
    assert measure.LOCAL_DATA_DIR == BASE_DIR / "data" / "local"
    assert measure.DEMO_DIR == BASE_DIR / "data" / "demo_emails"
    record = _load_script("record_demo_run.py")
    assert record.DEMO_RECORDINGS_DIR == BASE_DIR / "data" / "demo_recordings"
    assert record.DEMO_EMAIL.is_file()
    generate = _load_script("generate_benchmark_cases.py")
    assert generate.BENCH_DIR == BENCH


def test_measure_attacks_starts_from_the_repo_root():
    proc = subprocess.run([sys.executable, "backend/scripts/measure_attacks.py", "--help"], cwd=REPO,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "--runs" in proc.stdout


def test_generator_keeps_a_teammates_files_and_manifest_rows(tmp_path, monkeypatch):
    generate = _load_script("generate_benchmark_cases.py")
    first = generate.build_cases()[0]["file"]
    (tmp_path / "manifest.csv").write_text(
        "file,category,expected_label,expected_hc_ids\n"
        f"{first},teammate_category,SUSPICIOUS,HC-01\n"
        "teammate_case.eml,teammate_extra,SAFE,\n", encoding="utf-8")
    (tmp_path / first).write_bytes(b"teammate version")
    monkeypatch.setattr(generate, "BENCH_DIR", tmp_path)
    monkeypatch.setattr(generate, "MANIFEST_PATH", tmp_path / "manifest.csv")
    generate.main()
    rows = {r["file"]: r for r in csv.DictReader(open(tmp_path / "manifest.csv", encoding="utf-8"))}
    assert rows[first]["category"] == "teammate_category"
    assert rows[first]["expected_label"] == "SUSPICIOUS"
    assert "teammate_case.eml" in rows
    assert (tmp_path / first).read_bytes() == b"teammate version"
