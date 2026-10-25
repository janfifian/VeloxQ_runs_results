#!/usr/bin/env python
"""Copy the VeloxQ campaign on the synthetic suite into repository_ready (15.10.2026).

Source: ``artifacts/campaign/veloxq/<setting>/`` (written by
``scripts/veloxq_batch.py``), the campaign's logs in ``artifacts/campaign/``
(``veloxq_console.txt``, ``veloxq_run.log``, ``veloxq_prepare_*.log``) and the
analysis tables in ``artifacts/campaign/veloxq/analysis/`` (written by
``scripts/analyze_veloxq_campaign.py``).
Destination: ``repository_ready/veloxq_synthetic``.

Only complete settings are copied: 64 instances x 3 calls, every call with its
timetable. Before anything is copied, every call is checked:

* the timetable parses and carries the verifier's verdict;
* the job id agrees in ``jobs.jsonl``, the run record and the job-id file;
* the sample archive, the gzipped server file and the best state have the
  hashes the record gives; the server file decompresses to the recorded hash
  and size; the sample archive holds ``num_rep`` reads;
* the QUBO file on disk is the one the record decoded with and the one
  submitted;
* the record's instance is the registry entry of a file in
  ``repository_ready/instances/synthetic`` (instances are not copied again).

Calls whose QUBO file, submission or processing ran at a commit other than the
tag ``campaign-2026-10-qubo`` are listed in the README with the files in which
that commit differs from the tag. The analysis tables are copied only when
they cover exactly the copied settings. Everything is copied byte for byte
(each copy checked against its source), with ``SHA256SUMS`` and
``.gitattributes`` (no line-end conversion), and the README with the results
per setting and tier. Each run brings the destination to exactly this
content: files already there with the right hash are left untouched (the
folder is under a sync client: about 0.5 GB per setting), the rest is copied,
files no longer expected are removed. Run it again after more settings finish.

The repair runs in ``artifacts/campaign/veloxq_ls`` named in ``REPAIR_RUNS``
(``scripts/run_veloxq_ls_campaign.py``: the repair with the MILP's room-set
rows on every S3 call, and its continuation of the calls left invalid; the
same repair from an empty timetable on every instance, ``--empty-start``, and
its continuation, 21.10.2026) go to ``repair/<run>/``, with their console logs
in ``logs/`` and the tables of ``scripts/analyze_veloxq_repair.py`` in
``analysis/``. Every call is checked first: its files are there; its run
record names as input the deposited VeloxQ timetable of the call (for a
continuation, the repaired timetable it continues; for an empty start, the
empty timetable, deposited in ``repair/<run>/inputs/``) and the deposited
instance, by content hash; the verdict is of that timetable and instance; the
record's cost has the run's options.

Usage:
    python scripts/assemble_veloxq_campaign_deposit.py
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "artifacts" / "campaign" / "veloxq"
LOG_DIR = REPO / "artifacts" / "campaign"
LOG_FILES = ("veloxq_console.txt", "veloxq_run.log")
OUT = REPO / "repository_ready" / "veloxq_synthetic"
REGISTRY = REPO / "repository_ready" / "instances" / "registry.json"
TAG = "campaign-2026-10-qubo"
DATA_REPO = "https://github.com/janfifian/VeloxQ_runs_results"   # the raw outputs, outside the code repository
TIERS = ("easy", "medium", "hard", "extreme")
N_INSTANCES, N_REPS = 64, 3
CALL_FILES = ("_velox_solution.yaml", "_veloxq_samples_phase2.npz", "_veloxq_result_phase2.h5.gz",
              "_veloxq_best_state_phase2.npz", "_veloxq_job_id_phase2.txt", ".log")
ANALYSIS_FILES = ("calls.csv", "tiers.csv", "paired.csv", "topk.csv", "breakdown.csv",
                  "breakdown_tiers.csv", "tier_view.csv",
                  "energy_separation.csv", "optimum_neighbours.csv")   # the last two: check_energy_separation.py
# Copied into scripts/: the stand-alone check, the analysis, how the runs were
# made, this script, and the generator of the paper's tables.
SCRIPTS = (REPO / "scripts" / "verify_veloxq_deposit.py", REPO / "scripts" / "analyze_veloxq_campaign.py",
           REPO / "scripts" / "check_energy_separation.py",
           REPO / "scripts" / "veloxq_batch.py", REPO / "scripts" / "run_penalty_scenarios.py",
           REPO / "scripts" / "assemble_veloxq_campaign_deposit.py", REPO / "paper" / "figures" / "make_figures.py",
           REPO / "scripts" / "run_veloxq_ls_campaign.py", REPO / "scripts" / "run_local_search.py",
           REPO / "scripts" / "analyze_veloxq_repair.py", REPO / "checks" / "two_move_neighbourhood.py")
# The repair (scripts/run_veloxq_ls_campaign.py): the repair with the MILP's room-set rows on
# every S3 call, and its continuation of the calls it left invalid with the targeted k = 3 moves;
# the same from an empty timetable on every instance (the null-seed control), and its continuation.
REPAIR_SRC = REPO / "artifacts" / "campaign" / "veloxq_ls"
REPAIR_RUNS = ("S3_room_set_rows", "S3_room_set_rows_k3_targeted",
               "S3_room_set_rows_empty_start", "S3_room_set_rows_empty_start_k3_targeted")
REPAIR_CALL_FILES = ("_postLS.yaml", "_postLS_verdict.json", "_stats.json", "_log.txt", ".log")
REPAIR_RUN_FILES = ("settings.json", "calls.json", "summary.csv",       # and, where the run has them:
                    "rerun_calls.txt", "stuck_calls.txt", "two_move_neighbourhood.json")
REPAIR_LOG_FILES = ("veloxq_ls_room_sets_run.log",                     # under artifacts/campaign
                    "veloxq_ls/S3_room_set_rows_empty_start_driver.log",
                    "veloxq_ls/S3_room_set_rows_empty_start_k3_targeted_driver.log")
REPAIR_ANALYSIS_FILES = ("repair_calls.csv", "repair_tiers.csv", "repair_stuck.csv")
# The code a repair run uses (scripts/run_veloxq_ls_campaign.py, CODE_PATHS).
REPAIR_CODE = ("src", "cfg", "scripts/run_local_search.py", "scripts/_pipeline_helpers.py",
               "scripts/run_veloxq_ls_campaign.py")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


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


def content_sha256(path: Path) -> str:
    """The run records' instance hash: CRLF turned into LF first."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_yaml(path: Path) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def complete_settings() -> List[str]:
    """Settings with 64 x 3 submitted jobs, each with its timetable."""
    done = []
    for sdir in sorted(p for p in SRC.iterdir() if p.is_dir() and p.name.startswith("S")):
        entries = read_jsonl(sdir / "jobs.jsonl")
        if (len(entries) == N_INSTANCES * N_REPS
                and all((sdir / f"rep_{e['rep']}" / f"{e['stem']}_velox_solution.yaml").exists() for e in entries)):
            done.append(sdir.name)
    return done


def check_setting(setting: str, registry: Dict[str, dict]) -> Dict[str, Any]:
    """Every call of a setting checked (module docstring); returns the calls'
    results and the source hash of every file to copy."""
    import numpy as np
    sdir = SRC / setting
    entries = read_jsonl(sdir / "jobs.jsonl")
    if len({(e["stem"], e["rep"]) for e in entries}) != len(entries) or len({e["job_id"] for e in entries}) != len(entries):
        raise SystemExit(f"{setting}: duplicate calls or job ids in jobs.jsonl")
    if read_jsonl(sdir / "failed.jsonl"):
        raise SystemExit(f"{setting}: failed.jsonl lists failed jobs; a complete setting has none")
    hashes: Dict[Path, str] = {}
    cache_hash: Dict[str, str] = {}
    calls, commits = [], Counter()
    for e in entries:
        tag = f"{setting} {e['stem']} call {e['rep']}"
        prefix = sdir / f"rep_{e['rep']}" / e["stem"]
        md = load_yaml(Path(f"{prefix}_velox_solution.yaml")).get("metadata") or {}
        p2, ver = md.get("phase2") or {}, md.get("verifier") or {}
        if ver.get("n_violations") is None or not ver.get("statuses"):
            raise SystemExit(f"{tag}: the timetable has no verifier verdict")
        if p2.get("veloxq_job_id") != e["job_id"] or \
                Path(f"{prefix}_veloxq_job_id_phase2.txt").read_text(encoding="utf-8").strip() != e["job_id"]:
            raise SystemExit(f"{tag}: the job id differs between jobs.jsonl, the record and the job-id file")
        npz = Path(f"{prefix}_veloxq_samples_phase2.npz")
        hashes[npz] = sha256(npz)
        samples = p2.get("veloxq_samples_file") or {}
        with np.load(npz) as z:
            reads = int(z["num_occurrences"].sum())
        if hashes[npz] != samples.get("sha256") or reads != e["num_rep"] or samples.get("n_reads") != e["num_rep"]:
            raise SystemExit(f"{tag}: the sample archive differs from its record ({reads} reads)")
        gz = Path(f"{prefix}_veloxq_result_phase2.h5.gz")
        hashes[gz] = sha256(gz)
        raw = p2.get("veloxq_raw_result_file") or {}
        if hashes[gz] != raw.get("sha256_file_bytes") or \
                gunzip_identity(gz) != (raw.get("uncompressed_sha256"), raw.get("uncompressed_bytes")):
            raise SystemExit(f"{tag}: the server file differs from its record")
        best = Path(f"{prefix}_veloxq_best_state_phase2.npz")
        hashes[best] = sha256(best)
        if hashes[best] != (p2.get("best_state_file") or {}).get("sha256_file_bytes"):
            raise SystemExit(f"{tag}: the best state differs from its record")
        cache = sdir / "caches" / f"{e['stem']}.qubo_cache.h5"
        if e["stem"] not in cache_hash:
            cache_hash[e["stem"]] = hashes[cache] = sha256(cache)
        if not (cache_hash[e["stem"]] == (p2.get("qubo_cache_file") or {}).get("sha256_file_bytes")
                == (e.get("cache") or {}).get("sha256_file_bytes")):
            raise SystemExit(f"{tag}: the QUBO file on disk, decoded with and submitted differ")
        digest = (((md.get("instance") or {}).get("file")) or {}).get("sha256")
        row = registry.get(digest)
        if row is None or Path(row["instance"]).stem != e["stem"]:
            raise SystemExit(f"{tag}: its instance (sha256 {digest}) is not the deposited {e['stem']}.yaml")
        commits[("QUBO file", (p2.get("qubo_cache_code_version") or {}).get("commit"))] += 1
        commits[("submission", (e.get("code") or {}).get("commit"))] += 1
        commits[("processing", ((md.get("environment") or {}).get("code") or {}).get("commit"))] += 1
        status = ver.get("statuses") or {}
        calls.append({"stem": e["stem"], "tier": e["stem"].split("_")[0], "rep": e["rep"],
                      "V": int(ver["n_violations"]), "full": status.get("full") is True,
                      "solver_s": p2.get("veloxq_solver_time_seconds"),
                      "commit_qubo": (p2.get("qubo_cache_code_version") or {}).get("commit"),
                      "commit_submission": (e.get("code") or {}).get("commit"),
                      "commit_processing": ((md.get("environment") or {}).get("code") or {}).get("commit")})
    return {"calls": calls, "hashes": hashes, "commits": commits,
            "record": md, "setting_json": json.loads((sdir / "setting.json").read_text(encoding="utf-8"))}


def check_repair_run(name: str, settings: List[str], registry: Dict[str, dict]) -> Dict[str, Any]:
    """Every call of a repair run checked (module docstring); returns the calls, the run's
    options, the commits the calls ran at and the modified files the records list."""
    run = REPAIR_SRC / name
    options = json.loads((run / "settings.json").read_text(encoding="utf-8"))
    setting, source_run = options.get("setting"), options.get("input_run")
    empty_start = bool(options.get("empty_start"))
    if setting not in settings:
        raise SystemExit(f"repair run {name}: its setting {setting} is not in the deposit")
    room_set_rows = "--room-set-rows" in (options.get("extra") or [])
    calls, commits, modified = [], Counter(), set()
    for verdict_file in sorted(run.glob("rep_*/*_postLS_verdict.json")):
        stem = verdict_file.name[: -len("_postLS_verdict.json")]
        rep = verdict_file.parent.name
        tag = f"repair run {name}, {rep}/{stem}"
        for suffix in REPAIR_CALL_FILES:
            if not (verdict_file.parent / f"{stem}{suffix}").is_file():
                raise SystemExit(f"{tag}: {stem}{suffix} is missing")
        post = verdict_file.parent / f"{stem}_postLS.yaml"
        md = load_yaml(post).get("metadata") or {}
        source = (REPAIR_SRC / source_run / rep / f"{stem}_postLS.yaml" if source_run
                  else run / "inputs" / f"{stem}_empty.yaml" if empty_start
                  else SRC / setting / rep / f"{stem}_velox_solution.yaml")
        if (md.get("source_solution_file") or {}).get("sha256") != content_sha256(source):
            raise SystemExit(f"{tag}: the record's input is not {source.relative_to(REPO)}")
        if empty_start and load_yaml(source).get("lessons"):
            raise SystemExit(f"{tag}: the empty timetable {source.name} has lessons")
        inst = registry.get((md.get("source_instance_file") or {}).get("sha256"))
        if inst is None or Path(inst["instance"]).stem != stem:
            raise SystemExit(f"{tag}: the record's instance is not the deposited {stem}.yaml")
        verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
        if (verdict.get("solution_file") or {}).get("sha256") != content_sha256(post) or \
                (verdict.get("instance_file") or {}).get("sha256") != inst["sha256"]:
            raise SystemExit(f"{tag}: the verdict is not of this timetable and instance")
        if bool((md.get("cost_definition") or {}).get("room_set_rows")) != room_set_rows:
            raise SystemExit(f"{tag}: the record's cost does not have the run's options")
        code = (md.get("environment") or {}).get("code") or {}
        commits[code.get("commit")] += 1
        modified |= set(code.get("modified_tracked_files") or [])
        calls.append({"stem": stem, "tier": stem.split("_")[0], "rep": int(rep.split("_")[1]),
                      "full": (verdict.get("statuses") or {}).get("full") is True})
    jobs = [(e["stem"], e["rep"]) for e in read_jsonl(SRC / setting / "jobs.jsonl")]
    wanted = set(options["calls"]) if options.get("calls") else \
        {f"rep_0/{s}" for s, _ in jobs} if empty_start else {f"rep_{r}/{s}" for s, r in jobs}
    if {f"rep_{c['rep']}/{c['stem']}" for c in calls} != wanted:
        raise SystemExit(f"repair run {name}: its calls are not the {len(wanted)} its settings.json names")
    used = [f for f in modified if any(f == p or f.startswith(p + "/") for p in REPAIR_CODE)]
    if used:
        raise SystemExit(f"repair run {name}: the records list modified files the runs use: {used}")
    return {"calls": calls, "options": options, "commits": commits, "modified": sorted(modified)}


GENERATED = ("README.md", ".gitattributes", "SHA256SUMS")


def sync(expected: Dict[str, tuple]) -> tuple:
    """Make the destination hold exactly ``expected`` ({published path:
    (source file, or the bytes of a snapshot, sha256)}) besides the generated
    files: copy what is missing or differs (each copy checked against the
    hash), leave identical files untouched (a sync client need not upload
    them again), remove the rest. Returns (copied, unchanged, removed)."""
    copied = unchanged = removed = 0
    for rel, (src, digest) in sorted(expected.items()):
        dst = OUT / rel
        if dst.is_file() and sha256(dst) == digest:
            unchanged += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(src, bytes):
            dst.write_bytes(src)
        else:
            shutil.copy2(src, dst)
        if sha256(dst) != digest:
            raise SystemExit(f"copy differs from its source: {rel}")
        copied += 1
    keep = set(expected) | set(GENERATED)
    for p in sorted(OUT.rglob("*"), key=lambda q: len(q.parts), reverse=True):
        if p.is_file() and p.relative_to(OUT).as_posix() not in keep:
            p.unlink()
            removed += 1
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    return copied, unchanged, removed


def fmt(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "--"


def repair_command(name: str, options: Dict[str, Any]) -> str:
    """The driver's command line that made a repair run, from its settings.json."""
    cmd = [f"python scripts/run_veloxq_ls_campaign.py --settings {options['setting']}"]
    if options.get("input_run"):
        cmd.append(f"--input-run {options['input_run']}")
    if options.get("empty_start"):
        cmd.append("--empty-start")
    cmd.append(f"--output-name {name}")
    if options.get("calls"):
        cmd.append("--calls-file " + ("stuck_calls.txt" if (REPAIR_SRC / name / "stuck_calls.txt").exists()
                                      else "<list>"))
    cmd.append(f"--ks {' '.join(map(str, options['ks']))} --candidate-shortlist-k {options['candidate_shortlist_k']} "
               f"--max-outer-passes {options['max_outer_passes']} "
               f"--max-wall-seconds-per-pass {options['max_wall_seconds_per_pass']}")
    if options.get("extra"):
        cmd.append("--extra " + " ".join(options["extra"]))
    return " ".join(cmd)


def repair_readme(repair: Dict[str, Dict[str, Any]], tag_commit: str, with_tables: bool) -> List[str]:
    lines = [
        "## Repair of the S3 answers",
        "",
        "The repair of the paper (H1, then H2 with k = 1 and 2 and 10 candidate places per item, repeated until a "
        "full pass changes nothing, with no limit on time or passes) on the answer of every S3 call, with the "
        "room rows of the MILP in the first key of its cost (`--room-set-rows`: per 15-minute cell where a "
        "candidate slot starts and per room set, the lessons whose free admissible rooms lie inside the set fit "
        "in it in number and in seats, and the lessons that can use a clean room fit in the clean rooms); and "
        "the continuation of the calls it leaves invalid with the targeted moves at k = 3. Each call runs "
        "`scripts/run_local_search.py` on the call's QUBO file (the first key: violations of the time stage, "
        "15-minute-break and PR5 pairs, exceeded room rows of the MILP; the second: the weighted MILP objective), "
        "then the verifier with the exact room assignment. The commands (`scripts/run_veloxq_ls_campaign.py`):",
        "",
    ]
    for name, rr in repair.items():
        lines += [f"    {repair_command(name, rr['options'])}", ""]
    if "S3_room_set_rows" in repair and (REPAIR_SRC / "S3_room_set_rows" / "rerun_calls.txt").exists():
        lines += ["`S3_room_set_rows` ran in two batches with the same options: first the calls listed in "
                  "`rerun_calls.txt` (those left without a room assignment by a repair without the room-set rows, "
                  "which is not deposited), then the others.", ""]
    empty = [n for n, rr in repair.items() if rr["options"].get("empty_start")]
    for name in empty:
        calls = repair[name]["calls"]
        valid = ", ".join(f"{sum(c['full'] for c in calls if c['tier'] == t)} / {sum(c['tier'] == t for c in calls)} {t}"
                          for t in TIERS)
        lines += [f"`{name}` is the same repair from an empty timetable, once per instance (`--empty-start`, "
                  "21.10.2026: what the repair reaches without the solver); each call starts from the timetable "
                  f"without lessons in `inputs/` and is kept as call 0. Valid: {valid} instances."]
        for cont, rr in repair.items():
            if rr["options"].get("input_run") == name:
                done = rr["calls"]
                lines[-1] += (f" `{cont}` continues the instance it leaves invalid, `{done[0]['stem']}`, which "
                              f"{'ends valid' if done[0]['full'] else 'stays invalid'}." if len(done) == 1 else
                              f" `{cont}` continues the {len(done)} instances it leaves invalid; "
                              f"{sum(c['full'] for c in done)} of them end valid.")
        lines.append("")
    lines += ["Code: the commit each call ran at, from its run record."]
    for name, rr in repair.items():
        parts = [f"{c[:7]} ({n} call{'s' if n != 1 else ''})"
                 for c, n in sorted(rr["commits"].items(), key=lambda kv: -kv[1])]
        lines.append(f"- `{name}`: {', '.join(parts)}.")
    newest = max((c for rr in repair.values() for c in rr["commits"]),
                 key=lambda c: int(git("rev-list", "--count", c) or 0))
    for c in sorted({c for rr in repair.values() for c in rr["commits"]} - {newest}):
        files = git("diff", "--name-only", c, newest, "--", *REPAIR_CODE).splitlines()
        lines.append(f"- In the code the repair uses, {c[:7]} differs from {newest[:7]} only in "
                     f"{', '.join(f'`{f}`' for f in files) or 'nothing'}.")
    code = git("diff", "--name-only", tag_commit, newest, "--", *REPAIR_CODE).splitlines()
    lines.append(f"- In the code the repair uses, {newest[:7]} differs from the tag `{TAG}` in "
                 f"{', '.join(f'`{f}`' for f in code) or 'nothing'}: the room-set rows of the repair and the "
                 "driver's options.")
    modified = sorted({f for rr in repair.values() for f in rr["modified"]})
    if modified:
        lines.append(f"- The records mark the checkout as modified; the files they list "
                     f"({', '.join(f'`{f}`' for f in modified)}) are not used by the runs.")
    lines += [
        "",
        "Files, in `repair/<run>/` (`<stem>` the instance, `<r>` the call):",
        "",
        "| file | content |",
        "|---|---|",
        "| `settings.json` | the run's options (of its last invocation) and, for a continuation, the run it continues |",
        "| `calls.json`, `summary.csv` | seconds per call (repair and verification); one line per call: the cost "
        "before and after, the verifier's statuses, the search's seconds and cycles |",
        "| `rep_<r>/<stem>_postLS.yaml` | the repaired timetable with its run record: input timetable and instance "
        "(path and content hash), the cost's definition, the cost and its parts before and after, code version, "
        "command-line arguments |",
        "| `rep_<r>/<stem>_postLS_verdict.json` | the verifier's verdict on it: every check, and the exact room "
        "assignment (a room for every in-person lesson when one exists) |",
        "| `rep_<r>/<stem>_stats.json` | every cycle of the repair: the cost and the violations by rule before and "
        "after, seconds |",
        "| `rep_<r>/<stem>_log.txt`, `rep_<r>/<stem>.log` | the repair's log; the process log (repair and "
        "verification) |",
        "| `S3_room_set_rows/two_move_neighbourhood.json` | `checks/two_move_neighbourhood.py` on the calls the "
        "repair leaves invalid: for the course short of its minutes, what blocks each of its places, and how "
        "many moves of the missing lesson with at most one other lesson (every such move, not only the repair's "
        "10 candidates) give a valid timetable |",
        "| `S3_room_set_rows/rerun_calls.txt`, `<continuation>/stuck_calls.txt` | the calls of the "
        "first batch; the calls continued |",
    ]
    if empty:
        lines.append("| `" + "`, `".join(f"{n}/inputs/<stem>_empty.yaml" for n in empty) + "` | the timetable "
                     "without lessons an empty-start call begins from (the input its run record names) |")
    logs = [n.rsplit("/", 1)[-1] for n in REPAIR_LOG_FILES[1:] if (LOG_DIR / n).exists()]
    lines += [
        "",
        "`logs/veloxq_ls_room_sets_run.log` is the console of `S3_room_set_rows`"
        + (", " + ", ".join(f"`logs/{n}`" for n in logs) + " those of the empty-start runs" if logs else "")
        + ". The tables in `analysis/` "
        "(`scripts/analyze_veloxq_repair.py`; PyYAML only): per call (`repair_calls.csv`), per tier "
        "(`repair_tiers.csv`), the calls left invalid (`repair_stuck.csv`). The weighted objective is given only "
        "for timetables that pass every check, with its gap to the proven optimum of the weighted MILP "
        "(`E_opt` of `analysis/energy_separation.csv`).",
        "",
    ]
    if with_tables:
        tiers = list(csv.DictReader(open(SRC / "analysis" / "repair_tiers.csv", encoding="utf-8")))
        lines += ["| tier | calls valid | instances valid | at the MILP optimum | gap median (max), % | best call "
                  "per instance, median (max), % | search seconds median (max) |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for t in tiers:
            known = int(t["valid_calls_with_optimum"])
            lines.append(
                f"| {t['tier']} | {t['calls_valid']} / {t['calls']} | {t['instances_valid']} / {t['instances']} | "
                + (f"{t['calls_at_optimum']} / {known} | {fmt(t['gap_median'])} ({fmt(t['gap_max'])}) | "
                   f"{fmt(t['best_gap_median'])} ({fmt(t['best_gap_max'])})" if known else "-- | -- | --")
                + f" | {fmt(t['repair_seconds_median'])} ({fmt(t['repair_seconds_max'])}) |")
        stuck = list(csv.DictReader(open(SRC / "analysis" / "repair_stuck.csv", encoding="utf-8")))
        lines += ["", "Calls left invalid (`repair_stuck.csv`): the course short of its minutes, its places by the "
                  "number of lessons in the way (`clashing lessons: places`), the valid moves of at most two "
                  "lessons, and the continuation at k = 3:", "",
                  "| call | course | groups / students | places by clashing lessons | valid moves of 1 / 2 lessons "
                  "| continued: valid |", "|---|---:|---|---|---:|---|"]
        for s in stuck:
            lines.append(f"| `{s['instance']}` call {s['rep']} | {s['course']} ({s['missing_minutes']} min "
                         f"missing) | {s['groups']} / {s['students']} | {s['places_by_clashing_lessons']} | "
                         f"{s['valid_1_moves']} / {s['valid_2_moves']} | {s['continued_full']} |")
        lines.append("")
    lines += [
        "To check: `scripts/verify_veloxq_deposit.py` (*How to check*, above) checks every repair call's files "
        "and links (input timetable, instance and verdict by content hash) and recomputes the three tables from "
        "the records. The exhaustive check of the calls left invalid needs the project's code:",
        "",
        "    python checks/two_move_neighbourhood.py --run repository_ready/veloxq_synthetic/repair/S3_room_set_rows "
        "--caches repository_ready/veloxq_synthetic",
        "",
    ]
    return lines


def overrides_text(overrides: Dict[str, Any]) -> str:
    if not overrides:
        return "none (the configured encoding)"
    return ", ".join(f"`{k}` = {json.dumps(v)}" for k, v in overrides.items())


def readme(settings: List[str], checked: Dict[str, Dict[str, Any]], pending: List[str], tag_commit: str,
           off_tag: List[str], with_analysis: bool, repair: Dict[str, Dict[str, Any]],
           with_repair_tables: bool) -> str:
    first = checked[settings[0]]["record"]
    env = first.get("environment") or {}
    packages = env.get("packages") or {}
    vq = first.get("veloxq") or {}
    lines = [
        "# VeloxQ on the synthetic suite: penalty settings",
        "",
        f"**Settings in this folder: {', '.join(settings)}.** "
        + (f"Not yet run or not yet complete: {', '.join(pending)}; this folder is refreshed from the campaign's "
           "outputs with `scripts/assemble_veloxq_campaign_deposit.py`." if pending else "All planned settings are here.")
        + (" The repair of the S3 answers is in `repair/` (*Repair of the S3 answers*, at the end)." if repair else ""),
        "",
        f"The raw campaign outputs (the setting folders and `analysis/`) are published at {DATA_REPO}, in its "
        "folder `veloxq/`; this folder adds this README, `SHA256SUMS`, `.gitattributes`, `logs/` and `scripts/`, "
        "which can be copied into `veloxq/` there.",
        "",
        "## What was run",
        "",
        "The time-allocation stage (phase 2) of every certified synthetic instance (`../instances/synthetic`), "
        "compiled to a QUBO under each penalty setting and solved by VeloxQ:",
        "",
        f"- VeloxQ backend `{vq.get('backend')}`, `num_steps` {vq.get('num_steps')}, `num_rep` {vq.get('num_rep')} "
        f"(replicas, each returned as a sample); {N_REPS} independent calls per instance and setting. The SDK "
        f"(`veloxq_sdk` {packages.get('veloxq_sdk')}) takes no seed, so the calls are independent but cannot be "
        "replayed;",
        "- the jobs of a setting were submitted together and their results pulled when they finished; each call's "
        "timetable is decoded from its lowest-energy sample (the solver's answer), with no repair;",
        "- rules: every hard rule of the paper, room rows on 15-minute cells, the 15-minute break and PR5 "
        "(no synthetic instance has online lessons, so PR5 is empty there);",
        f"- code: tag `{TAG}` (commit {tag_commit[:7]}); decoding and checks on {env.get('platform')}, "
        f"Gurobi {packages.get('gurobi_library')} for the exact room assignment.",
        "",
        "| setting | what it is | overrides of the configured encoding |",
        "|---|---|---|",
    ]
    for s in settings:
        sj = checked[s]["setting_json"]
        lines.append(f"| {s} | {sj.get('description')} | {overrides_text(sj.get('overrides') or {})} |")
    lines += [
        "",
        "## Files",
        "",
        "One folder per setting (`<stem>` is the instance file name without `.yaml`, `<r>` the call, 1 to 3):",
        "",
        "| file | content |",
        "|---|---|",
        "| `setting.json` | the setting and its overrides |",
        "| `jobs.jsonl` | one line per submitted job: job id, submission time, upload and submission seconds, "
        "the hash of the uploaded Ising file and of the QUBO file, the code commit |",
        "| `caches/<stem>.qubo_cache.h5` | the QUBO as submitted: matrix, variable index, configuration, the room "
        "presolve's row counts and what each penalty had to exceed on the instance |",
        "| `rep_<r>/<stem>_velox_solution.yaml` | the timetable decoded from the lowest-energy sample, with the "
        "verifier's verdicts (and a room for each lesson when an exact room assignment exists) and the run "
        "record: code version, solver and library versions, job id, submission and pull times, VeloxQ's job "
        "statistics and timeline, matrix size and coefficient range, penalty requirements, instance sha256 |",
        "| `rep_<r>/<stem>_veloxq_samples_phase2.npz` | every sample VeloxQ returned: states packed eight variables "
        "per byte (in the order of `labels`), energies and occurrence counts as reported, vartype, solver info |",
        "| `rep_<r>/<stem>_veloxq_result_phase2.h5.gz` | the server's result file, gzipped (the record gives the "
        "sha256 of the uncompressed file) |",
        "| `rep_<r>/<stem>_veloxq_best_state_phase2.npz` | the lowest-energy sample whole (decision and auxiliary "
        "bits, in the QUBO's variable order) with its energy on the matrix |",
        "| `rep_<r>/<stem>_veloxq_job_id_phase2.txt`, `rep_<r>/<stem>.log` | the job id; the processing log |",
        "",
        "`logs/` holds the campaign's console transcripts and logs, `scripts/` the scripts (see *How to check*). "
        + ("`analysis/` holds the tables of the analysis of these files: per call (`calls.csv`), per setting "
           "and tier (`tiers.csv`), the settings per instance (`paired.csv`), the 16 lowest-energy samples of "
           "each call decoded and checked (`topk.csv`), how the lowest-energy sample and the sample with the "
           "fewest violations among the 16 break, rule by rule (`breakdown.csv`, per tier `breakdown_tiers.csv`), "
           "the settings side by side per tier (`tier_view.csv`); and, from `scripts/check_energy_separation.py`, "
           "where each call's samples lie relative to the best legal timetable, the MILP optimum "
           "(`energy_separation.csv`), and every timetable one move from that optimum on five instances "
           "(`optimum_neighbours.csv`)." if with_analysis else ""),
        "",
        "Each run record names its instance by the sha256 of the file's content (CRLF turned into LF); every one "
        "of them is the registry entry of a file in `../instances/synthetic`, which the assembly script checks. "
        "`SHA256SUMS` lists every file here: binary files by their bytes, text files (`.yaml`, `.jsonl`, `.json`, "
        "`.csv`, `.log`, `.txt`, `.md`, `.py`) by their content with Windows line ends turned into Unix ones, "
        "because git may store them with either. `sha256sum -c SHA256SUMS` holds on a checkout with Unix line "
        "ends; `scripts/verify_veloxq_deposit.py` holds on either. Every hash inside the run records is of a "
        "binary file or independent of line ends.",
        "",
        "## How to check",
        "",
        "**Without the project's code** (Python 3 with numpy, h5py and PyYAML), from this folder:",
        "",
        "    python scripts/verify_veloxq_deposit.py",
        "",
        "It checks every file against `SHA256SUMS`; every call's files against its run record (job id; hashes of "
        "the samples, of the server file, also decompressed, and of the best state; the QUBO file submitted and "
        "decoded); every call's energies on its deposited QUBO file (the best state has the recorded energy, it is "
        "the sample VeloxQ reported lowest, and the energy VeloxQ reported is that sample's energy on the matrix "
        "in spin form); and the verdicts in the records against `analysis/calls.csv` and `analysis/tier_view.csv`."
        + (" With `repair/`, also every repair call's files and links, and the repair tables recomputed from the "
           "records (*Repair of the S3 answers*, below)." if repair else ""),
        "",
        "**The analysis**, from a checkout of the project at the tag `" + TAG + "` (it needs the project's decoder "
        "and verifier, and Gurobi for the exact room assignment; copy `scripts/analyze_veloxq_campaign.py` into "
        "the checkout's `scripts/` if it is not there):",
        "",
        "    python scripts/analyze_veloxq_campaign.py --root repository_ready/veloxq_synthetic --out <folder> --top-k 16",
        "    python repository_ready/veloxq_synthetic/scripts/verify_veloxq_deposit.py --compare-analysis <folder>",
        "",
        "The first command recomputes the analysis tables in `analysis/` from the files here (the timetables "
        "decoded from the samples, the verifier's checks, the deletion of surplus lessons, the weighted MILP "
        "objective); the second compares them with the deposited tables cell by cell. The energy check, "
        "which also needs the MILP optima (`../milp_synthetic_weighted`):",
        "",
        "    python scripts/check_energy_separation.py --root repository_ready/veloxq_synthetic "
        "--milp repository_ready/milp_synthetic_weighted --out <folder> --neighbours easy_003_seed_1030 "
        "medium_005_seed_1050 medium_006_seed_1061 hard_008_seed_1084 hard_009_seed_1090",
        "",
        "**How the runs were made** (these need the project's code): `scripts/veloxq_batch.py` (the QUBO files, "
        "the submission, and the processing of each result), `scripts/run_penalty_scenarios.py` (the settings, "
        "`SCENARIOS`), `scripts/assemble_veloxq_campaign_deposit.py` (this folder), "
        "`scripts/make_figures.py` (the paper's tables, from `analysis/`).",
        "",
        "Verdicts: *V* = the number of violated hard constraints of the time stage (course hours, lesson blocks, "
        "overlaps of a lecturer or a group, availability, assigned lecturer) and of the room rows on 15-minute "
        "cells; *all checks* = V = 0, an exact assignment of rooms to the in-person lessons, the 15-minute break "
        "and PR5.",
        "",
    ]
    if off_tag:
        lines += ["## Calls not entirely at the tag", ""] + [f"- {x}" for x in off_tag] + [""]
    lines += [
        "## Results",
        "",
        "Lowest-energy sample of each call, before any repair. *Instances*: instances with V = 0 in at least one "
        "of their calls; *solver*: VeloxQ's reported solver time per call, seconds (median).",
        "",
        "| setting | tier | calls | calls with V = 0 | calls passing all checks | instances (V = 0 in some call) "
        "| median V | median solver |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in settings:
        by_tier = defaultdict(list)
        for c in checked[s]["calls"]:
            by_tier[c["tier"]].append(c)
        for tier in TIERS:
            cs = by_tier.get(tier, [])
            if not cs:
                continue
            best = defaultdict(lambda: 10 ** 9)
            for c in cs:
                best[c["stem"]] = min(best[c["stem"]], c["V"])
            lines.append(
                f"| {s} | {tier} | {len(cs)} | {sum(c['V'] == 0 for c in cs)} | {sum(c['full'] for c in cs)} | "
                f"{sum(v == 0 for v in best.values())} of {len(best)} | {fmt(median(c['V'] for c in cs), 1)} | "
                f"{fmt(median(c['solver_s'] for c in cs if c['solver_s'] is not None), 1)} |")
    if repair:
        lines += [""] + repair_readme(repair, tag_commit, with_repair_tables)
    return "\n".join(lines) + "\n"


def main() -> None:
    settings = complete_settings()
    if not settings:
        raise SystemExit(f"no complete setting in {SRC}")
    pending = sorted(p.name for p in SRC.iterdir() if p.is_dir() and p.name.startswith("S") and p.name not in settings)
    registry = {r["sha256"]: r for r in json.loads(REGISTRY.read_text(encoding="utf-8")) if r.get("instance_in_folder")}
    for row in registry.values():
        if content_sha256(REPO / "repository_ready" / "instances" / row["instance"]) != row["sha256"]:
            raise SystemExit(f"{row['instance']}: the deposited file does not have the registry hash")
    tag_commit = git("rev-parse", f"{TAG}^{{commit}}")
    checked = {}
    for s in settings:
        checked[s] = check_setting(s, registry)
        print(f"{s}: {len(checked[s]['calls'])} calls checked", flush=True)

    off_tag = []
    for s in settings:
        odd = defaultdict(list)                 # (stem, step, commit) -> calls
        for c in checked[s]["calls"]:
            for step in ("qubo", "submission", "processing"):
                commit = c[f"commit_{step}"]
                if commit != tag_commit:
                    odd[(c["stem"], step, commit or "")].append(c["rep"])
        for (stem, step, commit), reps in sorted(odd.items()):
            which = "every call" if len(reps) == N_REPS else \
                ("call " if len(reps) == 1 else "calls ") + ", ".join(map(str, sorted(reps)))
            what = {"qubo": "its QUBO file was built" if len(reps) == N_REPS else f"the QUBO file of {which} was built",
                    "submission": which + (" was" if len(reps) == 1 else " were") + " submitted",
                    "processing": which + (" was" if len(reps) == 1 else " were") + " processed"}[step]
            if not commit:
                off_tag.append(f"{s}, `{stem}`: {what} with no commit recorded.")
                continue
            files = git("diff", "--name-only", commit, tag_commit).splitlines()
            off_tag.append(f"{s}, `{stem}`: {what} at commit {commit[:7]}, which differs from the tag only in "
                           f"{', '.join(f'`{f}`' for f in files) or 'nothing'}.")

    repair = {}
    for name in REPAIR_RUNS:
        if (REPAIR_SRC / name / "settings.json").exists():
            repair[name] = check_repair_run(name, settings, registry)
            print(f"repair run {name}: {len(repair[name]['calls'])} calls checked", flush=True)
    with_repair_tables = False
    if repair and all((SRC / "analysis" / f).exists() for f in REPAIR_ANALYSIS_FILES):
        rows = list(csv.DictReader(open(SRC / "analysis" / "repair_calls.csv", encoding="utf-8")))
        main_run = repair.get("S3_room_set_rows")
        with_repair_tables = main_run is not None and \
            {(r["instance"], int(r["rep"]), r["full"] == "True") for r in rows} == \
            {(c["stem"], c["rep"], c["full"]) for c in main_run["calls"]}
        if not with_repair_tables:
            print("repair tables not copied: analysis/repair_calls.csv does not match the repair run "
                  "(run scripts/analyze_veloxq_repair.py first)")

    with_analysis = False
    calls_csv = SRC / "analysis" / "calls.csv"
    if calls_csv.exists():
        covered = {row["setting"] for row in csv.DictReader(open(calls_csv, encoding="utf-8"))}
        with_analysis = covered == set(settings) and all((SRC / "analysis" / f).exists() for f in ANALYSIS_FILES)
        if not with_analysis:
            print(f"analysis tables not copied: they cover {sorted(covered)}, the folder {settings} "
                  "(run scripts/analyze_veloxq_campaign.py --settings ... --top-k 16 first)")

    expected: Dict[str, tuple] = {}             # published path -> (source, sha256)

    def add(src: Path, rel: str, known: Dict[Path, str]) -> None:
        expected[rel] = (src, known.get(src) or sha256(src))

    for s in settings:
        known, sdir = checked[s]["hashes"], SRC / s
        for name in ("setting.json", "jobs.jsonl"):
            add(sdir / name, f"{s}/{name}", known)
        for cache in sorted((sdir / "caches").glob("*.qubo_cache.h5")):
            add(cache, f"{s}/caches/{cache.name}", known)
        for c in checked[s]["calls"]:
            for suffix in CALL_FILES:
                name = f"{c['stem']}{suffix}"
                add(sdir / f"rep_{c['rep']}" / name, f"{s}/rep_{c['rep']}/{name}", known)
    # Logs as a snapshot: a running campaign keeps appending to its log.
    for log in [LOG_DIR / n for n in LOG_FILES if (LOG_DIR / n).exists()] + sorted(LOG_DIR.glob("veloxq_prepare_*.log")):
        data = log.read_bytes()
        expected[f"logs/{log.name}"] = (data, hashlib.sha256(data).hexdigest())
    if with_analysis:
        for name in ANALYSIS_FILES:
            add(SRC / "analysis" / name, f"analysis/{name}", {})
    for name, rr in repair.items():
        run = REPAIR_SRC / name
        for fname in REPAIR_RUN_FILES:
            if (run / fname).is_file():
                add(run / fname, f"repair/{name}/{fname}", {})
        for c in rr["calls"]:
            for suffix in REPAIR_CALL_FILES:
                fname = f"{c['stem']}{suffix}"
                add(run / f"rep_{c['rep']}" / fname, f"repair/{name}/rep_{c['rep']}/{fname}", {})
            if rr["options"].get("empty_start"):
                fname = f"{c['stem']}_empty.yaml"
                add(run / "inputs" / fname, f"repair/{name}/inputs/{fname}", {})
    if repair:
        for log in [LOG_DIR / n for n in REPAIR_LOG_FILES if (LOG_DIR / n).exists()]:
            data = log.read_bytes()
            expected[f"logs/{log.name}"] = (data, hashlib.sha256(data).hexdigest())
    if with_repair_tables:
        for name in REPAIR_ANALYSIS_FILES:
            add(SRC / "analysis" / name, f"analysis/{name}", {})
    for script in SCRIPTS:
        add(script, f"scripts/{script.name}", {})

    OUT.mkdir(parents=True, exist_ok=True)
    copied, unchanged, removed = sync(expected)
    (OUT / "README.md").write_bytes(
        readme(settings, checked, pending, tag_commit, off_tag, with_analysis, repair,
               with_repair_tables).encode("utf-8"))
    (OUT / ".gitattributes").write_bytes(
        b"# Keep the bytes as they are: the hashes in the run records refer to them.\n* -text\n")
    # Text files are listed by their content with Windows line ends turned into Unix ones: git
    # stores them with either (the published repository has Unix ones), binary files by their bytes.
    text = (".yaml", ".jsonl", ".json", ".csv", ".log", ".txt", ".md", ".py")
    sums = {}
    for rel, (_src, digest) in list(expected.items()) + [(n, (None, sha256(OUT / n))) for n in ("README.md", ".gitattributes")]:
        is_text = Path(rel).suffix in text or Path(rel).name == ".gitattributes"
        sums[rel] = content_sha256(OUT / rel) if is_text else digest
    (OUT / "SHA256SUMS").write_bytes(("\n".join(f"{d}  {rel}" for rel, d in sorted(sums.items())) + "\n").encode())
    print(f"{OUT}: settings {', '.join(settings)} ({sum(len(checked[s]['calls']) for s in settings)} calls checked); "
          f"repair runs {', '.join(repair) or 'none'}; "
          f"{len(expected)} files: {copied} copied and checked, {unchanged} already there, {removed} removed; "
          "README and SHA256SUMS written" + (f"; not complete yet: {', '.join(pending)}" if pending else ""))


if __name__ == "__main__":
    main()
