#!/usr/bin/env python
"""Check the VeloxQ deposit (``repository_ready/veloxq_synthetic``) without the
project's code (16.10.2026). Needs only numpy, h5py and PyYAML.

1. ``SHA256SUMS`` (when present): every file it lists has that hash; text files are hashed
   with Windows line ends turned into Unix ones, so the list holds on either kind of checkout
   (git stores the text files of the published repository with Unix line ends).
2. Every call (``<setting>/jobs.jsonl``): the timetable's run record parses and
   carries the verifier's verdict; the job id agrees in ``jobs.jsonl``, the
   record and the job-id file; the sample archive, the gzipped server file and
   the best state have the hashes the record gives, the server file
   decompresses to the recorded hash and size, and the archive holds
   ``num_rep`` reads; the QUBO file is the one submitted and decoded.
3. Energies, from the deposited QUBO file of each call: the best state's
   energy is the one the record gives; the best state is the sample VeloxQ
   reported with the lowest energy; and that reported energy is the sample's
   energy on the matrix, up to the constant of the change of variables from
   binary to spin (VeloxQ solved the spin form) and single-precision rounding.
4. The tables: per setting and tier, the calls with V = 0 and passing every
   check, read from the records, agree with ``analysis/calls.csv``, and the
   instances with a valid timetable agree with ``analysis/tier_view.csv``.
5. The repair (``repair/<run>/``, when present): every call of a run has its
   files; its run record names as input the deposited VeloxQ timetable of the
   call (for a continuation, the repaired timetable it continues) and the
   call's instance, by content hash; the verdict is of that timetable and
   instance; the record's cost has the run's options; the run holds exactly
   the calls its ``settings.json`` names. The repair tables
   (``analysis/repair_*.csv``) are recomputed from the records with
   ``analyze_veloxq_repair.py`` (next to this script; PyYAML only) and
   compared with the deposited ones cell by cell.

``--compare-analysis DIR`` also compares the tables in DIR, written by
``scripts/analyze_veloxq_campaign.py --root <this folder> --out DIR`` from a
checkout of the project at the tag ``campaign-2026-10-qubo``, with the
deposited ones in ``analysis/``, cell by cell.

Usage (from the deposit folder, or with --root, e.g. the ``veloxq`` folder of a clone of
https://github.com/janfifian/VeloxQ_runs_results):
    python scripts/verify_veloxq_deposit.py
    python scripts/verify_veloxq_deposit.py --root VeloxQ_runs_results/veloxq
    python scripts/verify_veloxq_deposit.py --compare-analysis my_rerun
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import h5py
import numpy as np
import yaml

ANALYSIS_FILES = ("calls.csv", "tiers.csv", "paired.csv", "topk.csv", "breakdown.csv",
                  "breakdown_tiers.csv", "tier_view.csv")
REPAIR_ANALYSIS_FILES = ("repair_calls.csv", "repair_tiers.csv", "repair_stuck.csv")
REPAIR_RUN, REPAIR_CONTINUATION = "S3_room_set_rows", "S3_room_set_rows_k3_targeted"
REPAIR_CALL_FILES = ("_postLS.yaml", "_postLS_verdict.json", "_stats.json", "_log.txt", ".log")
TIERS = ("easy", "medium", "hard", "extreme")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def default_root() -> Path:
    here = Path(__file__).resolve().parents[1]
    if (here / "SHA256SUMS").exists():                 # run from inside the deposit
        return here
    return here / "repository_ready" / "veloxq_synthetic"   # run from the project's scripts/


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def gunzip_identity(path: Path) -> tuple:
    h, n = hashlib.sha256(), 0
    with gzip.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class Report:
    def __init__(self) -> None:
        self.problems: list = []

    def fail(self, msg: str) -> None:
        self.problems.append(msg)
        if len(self.problems) <= 30:
            print("  PROBLEM:", msg, flush=True)


TEXT_SUFFIXES = (".yaml", ".jsonl", ".json", ".csv", ".log", ".txt", ".md", ".py")


def listed_hash(path: Path) -> str:
    """The hash SHA256SUMS gives: of the bytes for binary files, of the content with Windows line
    ends turned into Unix ones for text files (git may store either)."""
    if path.suffix in TEXT_SUFFIXES or path.name == ".gitattributes":
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return sha256(path)


def check_sums(root: Path, rep: Report) -> int:
    if not (root / "SHA256SUMS").exists():
        return 0                                   # e.g. the raw outputs as published, without the list
    lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    for line in lines:
        digest, rel = line.split("  ", 1)
        p = root / rel
        if not p.is_file():
            rep.fail(f"SHA256SUMS lists a missing file: {rel}")
        elif listed_hash(p) != digest:
            rep.fail(f"hash differs from SHA256SUMS: {rel}")
    return len(lines)


def qubo_of(cache: Path) -> tuple:
    with h5py.File(cache, "r") as f:
        g = f["qubo"]
        return (int(g.attrs["n_vars"]), float(g.attrs["constant"]),
                g["Q_i"][:].astype(np.int64), g["Q_j"][:].astype(np.int64), g["Q_v"][:])


def check_calls(root: Path, setting: str, rep: Report) -> list:
    sdir = root / setting
    entries = read_jsonl(sdir / "jobs.jsonl")
    if len({e["job_id"] for e in entries}) != len(entries):
        rep.fail(f"{setting}: duplicate job ids in jobs.jsonl")
    calls, qubos = [], {}
    for e in entries:
        tag = f"{setting} {e['stem']} call {e['rep']}"
        prefix = sdir / f"rep_{e['rep']}" / e["stem"]
        try:
            md = (yaml.safe_load(open(f"{prefix}_velox_solution.yaml", encoding="utf-8")) or {}).get("metadata") or {}
        except Exception as exc:
            rep.fail(f"{tag}: the timetable does not parse ({exc!r})")
            continue
        p2, ver = md.get("phase2") or {}, md.get("verifier") or {}
        if ver.get("n_violations") is None or not ver.get("statuses"):
            rep.fail(f"{tag}: no verifier verdict")
            continue
        job_file = Path(f"{prefix}_veloxq_job_id_phase2.txt").read_text(encoding="utf-8").strip()
        if not (p2.get("veloxq_job_id") == e["job_id"] == job_file):
            rep.fail(f"{tag}: the job id differs between jobs.jsonl, the record and the job-id file")
        npz = Path(f"{prefix}_veloxq_samples_phase2.npz")
        samples = p2.get("veloxq_samples_file") or {}
        if sha256(npz) != samples.get("sha256"):
            rep.fail(f"{tag}: the sample archive differs from its record")
        gz = Path(f"{prefix}_veloxq_result_phase2.h5.gz")
        raw = p2.get("veloxq_raw_result_file") or {}
        if sha256(gz) != raw.get("sha256_file_bytes") or \
                gunzip_identity(gz) != (raw.get("uncompressed_sha256"), raw.get("uncompressed_bytes")):
            rep.fail(f"{tag}: the server file differs from its record")
        best_file = Path(f"{prefix}_veloxq_best_state_phase2.npz")
        if sha256(best_file) != (p2.get("best_state_file") or {}).get("sha256_file_bytes"):
            rep.fail(f"{tag}: the best state differs from its record")
        cache = sdir / "caches" / f"{e['stem']}.qubo_cache.h5"
        if cache not in qubos:
            qubos.clear()                                # one instance at a time
            qubos[cache] = (sha256(cache), qubo_of(cache))
        digest, (n, const, Qi, Qj, Qv) = qubos[cache]
        if not (digest == (p2.get("qubo_cache_file") or {}).get("sha256_file_bytes")
                == (e.get("cache") or {}).get("sha256_file_bytes")):
            rep.fail(f"{tag}: the QUBO file differs from the one submitted or decoded")

        # 3. energies
        with np.load(best_file) as b:
            x = np.unpackbits(b["bits"])[: int(b["n_vars"])].astype(np.float64)
        e_best = float(np.dot(Qv, x[Qi] * x[Qj]) + const)
        if not math.isclose(e_best, float(p2.get("energy")), rel_tol=1e-9, abs_tol=1e-3):
            rep.fail(f"{tag}: the best state's energy on the QUBO file is {e_best}, the record says {p2.get('energy')}")
        with np.load(npz) as z:
            states = np.unpackbits(z["bits"], axis=1)[:, : int(z["n_vars"])]
            labels = np.array([int(v) for v in z["labels"]])
            energy = z["energy"]
            reads = int(z["num_occurrences"].sum())
        if reads != e["num_rep"]:
            rep.fail(f"{tag}: {reads} reads, {e['num_rep']} requested")
        lowest = np.flatnonzero(energy == energy.min())
        matches = False
        for i in lowest:
            xs = np.zeros(n)
            xs[labels] = states[i]
            if np.array_equal(xs, x):
                matches = True
                break
        if not matches:
            rep.fail(f"{tag}: the best state is not the sample VeloxQ reported with the lowest energy")
        diag = Qi == Qj
        offset = const + Qv[diag].sum() / 2 + Qv[~diag].sum() / 4
        reported = float(energy.min())
        if not math.isclose(e_best - offset, reported, rel_tol=1e-6, abs_tol=1.0):
            rep.fail(f"{tag}: VeloxQ reported {reported} for its lowest sample; on the matrix it is "
                     f"{e_best - offset} (spin form)")
        status = ver.get("statuses") or {}
        calls.append({"setting": setting, "instance": e["stem"], "tier": e["stem"].split("_")[0], "rep": e["rep"],
                      "V": int(ver["n_violations"]), "full": status.get("full") is True,
                      "instance_sha256": (((md.get("instance") or {}).get("file")) or {}).get("sha256")})
    return calls


def content_sha256(path: Path) -> str:
    """The run records' hash of a text file: CRLF turned into LF first."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def check_repair(root: Path, calls: list, rep: Report) -> int:
    """Step 5 for every run in repair/; returns the number of calls checked."""
    instance_of = {(c["setting"], c["instance"], c["rep"]): c["instance_sha256"] for c in calls}
    n = 0
    for run in sorted(p for p in (root / "repair").iterdir() if p.is_dir()):
        options = json.loads((run / "settings.json").read_text(encoding="utf-8"))
        setting, source_run = options.get("setting"), options.get("input_run")
        room_set_rows = "--room-set-rows" in (options.get("extra") or [])
        seen = set()
        for verdict_file in sorted(run.glob("rep_*/*_postLS_verdict.json")):
            stem = verdict_file.name[: -len("_postLS_verdict.json")]
            r = int(verdict_file.parent.name.split("_")[1])
            tag = f"repair {run.name} {verdict_file.parent.name}/{stem}"
            seen.add(f"{verdict_file.parent.name}/{stem}")
            n += 1
            missing = [s for s in REPAIR_CALL_FILES if not (verdict_file.parent / f"{stem}{s}").is_file()]
            if missing:
                rep.fail(f"{tag}: missing {missing}")
                continue
            post = verdict_file.parent / f"{stem}_postLS.yaml"
            md = (yaml.safe_load(open(post, encoding="utf-8")) or {}).get("metadata") or {}
            source = (root / "repair" / source_run / verdict_file.parent.name / f"{stem}_postLS.yaml" if source_run
                      else root / setting / verdict_file.parent.name / f"{stem}_velox_solution.yaml")
            if (md.get("source_solution_file") or {}).get("sha256") != content_sha256(source):
                rep.fail(f"{tag}: the record's input is not {source.relative_to(root)}")
            instance = instance_of.get((setting, stem, r))
            verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
            if not (instance and (md.get("source_instance_file") or {}).get("sha256") == instance
                    == (verdict.get("instance_file") or {}).get("sha256")):
                rep.fail(f"{tag}: the record or the verdict names another instance than the VeloxQ call")
            if (verdict.get("solution_file") or {}).get("sha256") != content_sha256(post):
                rep.fail(f"{tag}: the verdict is not of this timetable")
            if bool((md.get("cost_definition") or {}).get("room_set_rows")) != room_set_rows:
                rep.fail(f"{tag}: the record's cost does not have the run's options")
        wanted = set(options["calls"]) if options.get("calls") else \
            {f"rep_{c['rep']}/{c['instance']}" for c in calls if c["setting"] == setting}
        if seen != wanted:
            rep.fail(f"repair {run.name}: {len(seen)} calls, its settings.json names {len(wanted)}")
    return n


def check_repair_tables(root: Path, rep: Report) -> None:
    """The repair tables recomputed from the records (analyze_veloxq_repair.py) and compared."""
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import analyze_veloxq_repair as ar
    optima = {}
    for r in read_csv(root / "analysis" / "energy_separation.csv"):
        optima.setdefault(r["instance"], float(r["E_opt"]))
    calls = ar.calls_of(root / "repair" / REPAIR_RUN, optima)
    continued = {(c["instance"], c["rep"]): c for c in ar.calls_of(root / "repair" / REPAIR_CONTINUATION, optima)}
    two_move = json.loads((root / "repair" / REPAIR_RUN / "two_move_neighbourhood.json").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="repair_tables_"))
    ar.write_csv(tmp / "repair_calls.csv", ar.CALL_COLUMNS, calls)
    ar.write_csv(tmp / "repair_tiers.csv", ar.TIER_COLUMNS, ar.tiers_of(calls))
    ar.write_csv(tmp / "repair_stuck.csv", ar.STUCK_COLUMNS, ar.stuck_of(calls, two_move, continued))
    compare_tables(root, tmp, REPAIR_ANALYSIS_FILES, rep)


def check_tables(root: Path, calls: list, rep: Report) -> None:
    rows = {(r["setting"], r["instance"], int(r["rep"])): r for r in read_csv(root / "analysis" / "calls.csv")}
    for c in calls:
        r = rows.get((c["setting"], c["instance"], c["rep"]))
        if r is None:
            rep.fail(f"analysis/calls.csv has no row for {c['setting']} {c['instance']} call {c['rep']}")
        elif int(float(r["V"])) != c["V"] or (r["full"] == "True") != c["full"]:
            rep.fail(f"analysis/calls.csv disagrees with the record of {c['setting']} {c['instance']} call {c['rep']}")
    valid = defaultdict(set)
    for c in calls:
        if c["full"]:
            valid[(c["setting"], c["tier"])].add(c["instance"])
    for r in read_csv(root / "analysis" / "tier_view.csv"):
        n = len(valid.get((r["setting"], r["tier"]), ()))
        if int(float(r["instances_all_checks_lowest_energy"])) != n:
            rep.fail(f"analysis/tier_view.csv: {r['setting']} {r['tier']} says "
                     f"{r['instances_all_checks_lowest_energy']} valid instances, the records {n}")


def same_cell(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        fa, fb = float(a), float(b)
    except ValueError:
        return False
    return math.isclose(fa, fb, rel_tol=1e-9, abs_tol=1e-9) or (math.isnan(fa) and math.isnan(fb))


def compare_analysis(root: Path, other: Path, rep: Report) -> None:
    names = ANALYSIS_FILES + (REPAIR_ANALYSIS_FILES if (root / "analysis" / "repair_calls.csv").exists() else ())
    compare_tables(root, other, names, rep)


def compare_tables(root: Path, other: Path, names: tuple, rep: Report) -> None:
    for name in names:
        mine, theirs = root / "analysis" / name, other / name
        if not theirs.exists():
            rep.fail(f"{other / name} is missing")
            continue
        a, b = read_csv(mine), read_csv(theirs)
        if len(a) != len(b) or (a and set(a[0]) != set(b[0])):
            rep.fail(f"{name}: {len(b)} rows / columns differ from the deposited {len(a)} rows")
            continue
        bad = [(i, k) for i, (ra, rb) in enumerate(zip(a, b)) for k in ra if not same_cell(ra[k], rb[k])]
        if bad:
            rep.fail(f"{name}: {len(bad)} cells differ, first at row {bad[0][0] + 2}, column {bad[0][1]}")
        else:
            print(f"  {name}: identical ({len(a)} rows)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=default_root(), help="the deposit folder")
    ap.add_argument("--settings", nargs="*", help="default: every setting folder")
    ap.add_argument("--compare-analysis", type=Path, help="a folder of re-computed analysis tables")
    args = ap.parse_args()
    root = args.root.resolve()
    rep = Report()
    print(f"deposit: {root}")
    n_listed = check_sums(root, rep)
    print(f"1. SHA256SUMS: {n_listed} files checked" if n_listed else "1. SHA256SUMS: none here, skipped", flush=True)
    settings = args.settings or sorted(p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("S"))
    calls = []
    for s in settings:
        got = check_calls(root, s, rep)
        calls += got
        print(f"2-3. {s}: {len(got)} calls checked (files, job ids, hashes, energies)", flush=True)
    if not args.settings:
        check_tables(root, calls, rep)
        print("4. analysis tables checked against the records")
        if (root / "repair").is_dir():
            n = check_repair(root, calls, rep)
            print(f"5. repair: {n} calls checked (files, input, instance and verdict by content hash, options)")
            if (root / "analysis" / "repair_calls.csv").exists():
                print("   repair tables recomputed from the records:")
                check_repair_tables(root, rep)
    if args.compare_analysis:
        print(f"comparing {args.compare_analysis} with analysis/:")
        compare_analysis(root, args.compare_analysis.resolve(), rep)
    print("all checks passed" if not rep.problems else f"{len(rep.problems)} problems")
    return 0 if not rep.problems else 1


if __name__ == "__main__":
    sys.exit(main())
