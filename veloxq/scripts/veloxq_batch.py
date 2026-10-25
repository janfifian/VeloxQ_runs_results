#!/usr/bin/env python
"""VeloxQ campaign on the certified synthetic instances, setting by setting, in
batches (13.10.2026).

A setting is one of the penalty scenarios S0-S6 of
``scripts/run_penalty_scenarios.py`` (encoding and penalties; described in
Section 7.6 of the paper and in the deposit's README). For one setting:

  prepare  build the setting's QUBO cache of every instance (local, no VeloxQ);
           the cache's metadata also records the setting, the room presolve's
           row counts and what each penalty had to exceed;
  submit   upload each instance's Ising file once and submit --reps jobs on it
           without waiting; every job id is appended to ``jobs.jsonl`` (fsync'd)
           the moment VeloxQ assigns it, so nothing submitted can be lost;
  pull     ask VeloxQ for the state of every job not saved yet. Each finished
           job is processed in its own process (``_process``): every returned
           sample, the server's result file, the decoded best state, the
           timetable with the verifier's verdicts and the full run record, as
           ``scripts/benchmark_pipeline.py --run-qubo-veloxq`` writes them.
           ``--wait S`` keeps pulling every S seconds until no job is pending
           or running;
  status   the state of every job, from VeloxQ;
  run      prepare, submit and pull --wait, for each setting in turn.

Outputs, per setting: ``artifacts/campaign/veloxq/<setting>/`` with
``setting.json`` (the overrides), ``caches/<instance>.qubo_cache.h5``,
``jobs.jsonl`` (one line per submitted job), ``failed.jsonl`` (jobs VeloxQ
reported failed or canceled) and ``rep_<r>/<instance>_velox_solution.yaml``
with ``_veloxq_samples_phase2.npz``, ``_veloxq_result_phase2.h5.gz`` (gzipped),
``_veloxq_best_state_phase2.npz``, ``_veloxq_job_id_phase2.txt`` and the
process log ``<instance>.log``.

No default budget: --reps, --num-steps and --num-rep are required. The script
refuses to submit with uncommitted changes in the code the runs use, and
checks every instance file against the deposit's registry. The local search on
the pulled samples is a separate step: ``scripts/run_veloxq_ls_campaign.py``.

Other instances (19.10.2026): --instance-files takes instance files instead of
the synthetic suite (each must be a certified entry of the registry, e.g.
``artifacts/3studies/3_studies_instance.yaml``), and --out-name puts the outputs
in ``artifacts/campaign/<out-name>/<setting>/`` instead of
``artifacts/campaign/veloxq/``, so the synthetic campaign's folders stay as
deposited. Every command on those outputs (pull, status) takes the same
--out-name.

Examples:
    python scripts/veloxq_batch.py run --settings S0 S3 --reps 3 --num-steps 10000 --num-rep 4096 --wait 60
    python scripts/veloxq_batch.py status --settings S0
    python scripts/veloxq_batch.py pull --settings S0 --wait 60
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import benchmark_pipeline as BP  # noqa: E402  (loads .env with override, sets up the environment)
from run_milp_campaign import check_registry, instances  # noqa: E402
from run_penalty_scenarios import SCENARIOS  # noqa: E402

from etpmachine import ETPMachine_DataLoader as DataLoader  # noqa: E402
from etpmachine import ETPMachine_QUBO as QUBOModule  # noqa: E402
from etpmachine.utils import run_record  # noqa: E402

OUT_ROOT = REPO / "artifacts" / "campaign" / "veloxq"
INSTANCES = REPO / "repository_ready" / "instances" / "synthetic"
PROBLEM_PREFIX = "campaign-2026-10"
CODE_PATHS = ("src", "cfg", "scripts/benchmark_pipeline.py", "scripts/_pipeline_helpers.py",
              "scripts/_veloxq_windows_fix.py", "scripts/veloxq_batch.py", "scripts/run_penalty_scenarios.py",
              "scripts/run_milp_campaign.py")
UNFINISHED = {"pending", "running", "created", "queued"}


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def setting_dir(setting: str) -> Path:
    return OUT_ROOT / setting


def cache_path(setting: str, stem: str) -> Path:
    return setting_dir(setting) / "caches" / f"{stem}.qubo_cache.h5"


def prefix_of(setting: str, stem: str, rep: int) -> Path:
    return setting_dir(setting) / f"rep_{rep}" / stem


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    """One line, flushed to the disk before anything else happens."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def uncommitted_code() -> List[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", *CODE_PATHS],
                         cwd=REPO, capture_output=True, text=True).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def job_status(job: Any) -> str:
    status = getattr(job, "status", "")
    return str(getattr(status, "value", status) or "").lower()


def plain(obj: Any) -> Any:
    """The SDK's pydantic objects (job statistics, timeline) as plain data."""
    if isinstance(obj, (list, tuple)):
        return [plain(x) for x in obj]
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return run_record.json_safe(dump(mode="json"))
        except Exception:
            pass
    return run_record.json_safe(obj)


PROCESS_FAILED: set = set()   # jobs whose processing failed in this session: not retried


def gzip_in_place(path: Path) -> Dict[str, Any]:
    """Replace ``path`` by ``path.gz`` (deterministic: no name or time in the
    header). The server's result file holds a byte per spin, about eight
    times what its content needs; the identity keeps the uncompressed hash,
    so the exact server bytes stay checkable after ``gunzip``."""
    import gzip
    import hashlib
    data = path.read_bytes()
    gz = path.with_name(path.name + ".gz")
    with open(gz, "wb") as raw_fh, gzip.GzipFile(filename="", mode="wb", fileobj=raw_fh, mtime=0) as fh:
        fh.write(data)
    identity = run_record.file_identity(gz)
    identity.update({"compression": "gzip", "uncompressed_sha256": hashlib.sha256(data).hexdigest(),
                     "uncompressed_bytes": len(data)})
    path.unlink()
    return identity


# ------------------------------------------------------------------ prepare

def prepare(setting: str, files: List[Path]) -> None:
    """Every instance's QUBO cache for the setting, built locally."""
    from etpmachine.ETPMachine_ProblemInstance import ProblemInstance
    from etpmachine.qubo_io import save_qubo_cache
    description, overlay = SCENARIOS[setting]
    sdir = setting_dir(setting)
    (sdir / "caches").mkdir(parents=True, exist_ok=True)
    (sdir / "setting.json").write_text(json.dumps(
        {"setting": setting, "description": description, "overrides": overlay,
         "base_config": "cfg/qubo_cfg.yaml"}, indent=1), encoding="utf-8")
    for k, f in enumerate(files, 1):
        cache = cache_path(setting, f.stem)
        if cache.exists():
            continue
        t0 = time.time()
        pi = ProblemInstance.from_yaml(str(f))
        pi.rebuild_derived()
        pi.apply_to_data_loader(DataLoader, ensure_derived=False)
        t_load = time.time() - t0
        t0 = time.time()
        model = QUBOModule.TimeAllocationQUBO(pi, config=dict(overlay))
        model.build(verbose=False)
        t_build = time.time() - t0
        # What each penalty must exceed on this instance, for every setting (the
        # model computes it only when its penalty profile uses it).
        from etpmachine.utils.penalty_bounds import required_penalties
        requirements = model.penalty_requirements or required_penalties(model.data, model.config)
        tmp = cache.with_suffix(".h5.partial")
        save_qubo_cache(tmp, qubo=model.qubo, x_index=model.x_index, pi=pi, config=model.config,
                        extra_metadata={
                            "source_yaml": str(f), "source_sha256": run_record.content_sha256(f.read_bytes()),
                            "setting": setting, "setting_overrides": overlay,
                            "room_presolve_stats": run_record.json_safe(model.room_presolve_stats),
                            "penalty_requirements": run_record.json_safe(requirements),
                            "penalty_profile_set_penalties": model.penalty_requirements is not None,
                            "load_time_seconds": round(t_load, 3), "build_time_seconds": round(t_build, 3),
                            "code_version": run_record.code_version(REPO),
                        })
        tmp.replace(cache)
        print(f"[{setting} prepare {k}/{len(files)}] {f.stem}: n_vars {model.qubo.n_vars:,}, "
              f"|Q| {len(model.qubo.Q):,}, build {t_build:.1f} s", flush=True)


# ------------------------------------------------------------------ submit

def _velox_sdk():
    from veloxq_sdk.config import VeloxQAPIConfig
    cfg = VeloxQAPIConfig.instance()
    cfg.multipart_upload_thread_count = 4
    cfg.multipart_upload_chunk_size = 32 * 1024 * 1024
    cfg.max_single_upload_size = 64 * 1024 * 1024
    return QUBOModule._import_veloxq_sdk()


def _problem(name: str) -> Any:
    from veloxq_sdk import Problem
    existing = [p for p in Problem.get_problems(name=name, limit=5) if p.name == name]
    return existing[0] if existing else Problem.create(name=name)


def _retry(what: str, fn, attempts: int = 3):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # network resets, rate limits
            last = exc
            print(f"  {what} failed (attempt {attempt}/{attempts}): {str(exc).splitlines()[0][:200]}", flush=True)
            time.sleep(10 * attempt)
    raise RuntimeError(f"{what} failed {attempts} times: {last}")


def submit(setting: str, files: List[Path], args: argparse.Namespace) -> int:
    from etpmachine.qubo_io import write_veloxq_ising_h5_from_cache
    sdir = setting_dir(setting)
    jobs_file = sdir / "jobs.jsonl"
    have = {(e["stem"], e["rep"]) for e in read_jsonl(jobs_file)}
    todo = [(f, r) for f in files for r in range(1, args.reps + 1) if (f.stem, r) not in have]
    if not todo:
        print(f"[{setting} submit] every job is already submitted", flush=True)
        return 0
    _dimod, File, Solver, Params, backends = _velox_sdk()
    from veloxq_sdk import File as VeloxFile
    problem = _retry("problem lookup", lambda: _problem(f"{PROBLEM_PREFIX}_{setting}"))
    solver = Solver(parameters=Params(num_rep=args.num_rep, num_steps=args.num_steps),
                    backend=backends[args.backend]())
    code = run_record.code_version(REPO)
    n = 0
    for f in files:
        reps = [r for (g, r) in todo if g == f]
        if not reps:
            continue
        cache = cache_path(setting, f.stem)
        if not cache.exists():
            raise SystemExit(f"{cache} missing: run prepare first")
        tmp_dir = Path(tempfile.mkdtemp(prefix="velox_batch_"))
        ising = tmp_dir / f"{f.stem}_{setting}_ising.h5"
        write_veloxq_ising_h5_from_cache(cache, ising, verbose=False)
        ising_id = run_record.file_identity(ising)
        t0 = time.time()
        file_obj = _retry(f"upload {f.stem}",
                          lambda: VeloxFile.from_path(str(ising), problem=problem, force=True))
        upload_s = round(time.time() - t0, 3)
        for r in reps:
            t1 = time.time()
            job = _retry(f"submit {f.stem} rep {r}", lambda: solver.submit(file_obj))
            entry = {
                "setting": setting, "stem": f.stem, "tier": f.stem.split("_")[0], "rep": r,
                "instance": str(f.relative_to(REPO)).replace("\\", "/"),
                "job_id": getattr(job, "id", None), "submitted_at": now(),
                "submit_seconds": round(time.time() - t1, 3), "upload_seconds": upload_s,
                "backend": args.backend, "num_steps": args.num_steps, "num_rep": args.num_rep,
                "problem": {"name": getattr(problem, "name", None), "id": str(getattr(problem, "id", ""))},
                "file_id": str(getattr(file_obj, "id", "")),
                "ising_h5": {"name": ising.name, "sha256": ising_id.get("sha256"), "bytes": ising_id.get("bytes")},
                "cache": run_record.file_identity(cache),
                "code": {"commit": code.get("commit"), "describe": code.get("describe")},
            }
            append_jsonl(jobs_file, entry)
            n += 1
            print(f"[{setting} submit] {f.stem} rep {r}: job {entry['job_id']}", flush=True)
        for p in (ising, tmp_dir):
            try:
                p.unlink() if p.is_file() else p.rmdir()
            except OSError:
                pass
    return n


# ------------------------------------------------------------------ pull

def solution_path(entry: Dict[str, Any]) -> Path:
    return Path(f"{prefix_of(entry['setting'], entry['stem'], entry['rep'])}_velox_solution.yaml")


def pull_once(setting: str) -> Dict[str, int]:
    from veloxq_sdk import Job
    sdir = setting_dir(setting)
    entries = read_jsonl(sdir / "jobs.jsonl")
    failed = {e["job_id"] for e in read_jsonl(sdir / "failed.jsonl")}
    counts = {"saved": 0, "processed_now": 0, "unfinished": 0, "failed": 0, "process_errors": 0}
    for e in entries:
        if solution_path(e).exists():
            counts["saved"] += 1
            continue
        if e["job_id"] in failed:
            counts["failed"] += 1
            continue
        if e["job_id"] in PROCESS_FAILED:
            counts["process_errors"] += 1
            continue
        job = _retry(f"status of {e['job_id']}", lambda: Job.from_id(e["job_id"]))
        state = job_status(job)
        if state == "completed":
            prefix = prefix_of(setting, e["stem"], e["rep"])
            prefix.parent.mkdir(parents=True, exist_ok=True)
            with open(f"{prefix}.log", "w", encoding="utf-8") as log:
                rc = subprocess.run([sys.executable, str(Path(__file__)), "_process", "--setting", setting,
                                     "--job-id", e["job_id"], "--out-name", OUT_ROOT.name], cwd=REPO, stdout=log,
                                    stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}).returncode
            if rc == 0 and solution_path(e).exists():
                counts["processed_now"] += 1
                counts["saved"] += 1
                print(f"[{setting} pull] {e['stem']} rep {e['rep']}: saved", flush=True)
            else:
                PROCESS_FAILED.add(e["job_id"])
                counts["process_errors"] += 1
                print(f"[{setting} pull] {e['stem']} rep {e['rep']}: processing FAILED (exit {rc}); "
                      f"see {prefix}.log; the job stays on the server and a later pull retries it", flush=True)
        elif state in ("failed", "canceled", "cancelled"):
            append_jsonl(sdir / "failed.jsonl", {**e, "status": state, "noted_at": now(),
                                                 "status_message": str(getattr(job, "status_message", ""))})
            counts["failed"] += 1
            print(f"[{setting} pull] {e['stem']} rep {e['rep']}: job {state}", flush=True)
        else:
            counts["unfinished"] += 1
    return counts


def pull(setting: str, wait: Optional[float]) -> Dict[str, int]:
    while True:
        counts = pull_once(setting)
        print(f"[{setting} pull] {counts['saved']} saved, {counts['unfinished']} pending or running, "
              f"{counts['failed']} failed, {counts['process_errors']} processing errors ({now()})", flush=True)
        if wait is None or (counts["unfinished"] == 0 and counts["process_errors"] == 0):
            return counts
        if counts["unfinished"] == 0:            # only processing errors left: retrying will not help
            return counts
        time.sleep(wait)


def process(setting: str, job_id: str) -> int:
    """One finished job: download what VeloxQ returned, then :func:`finish`."""
    from veloxq_sdk import Job
    entry = next(e for e in read_jsonl(setting_dir(setting) / "jobs.jsonl") if e["job_id"] == job_id)
    job = Job.from_id(job_id)
    pulled_at = now()
    return finish(setting, entry, job, job.result, pulled_at)


def finish(setting: str, entry: Dict[str, Any], job: Any, response: Any, pulled_at: str) -> int:
    """Archive every returned sample and the server's file, decode the best
    sample, verify the timetable and save it with the full run record."""
    from etpmachine.qubo_io import load_qubo_headline_from_h5, load_x_index_from_h5, qubo_energy_from_h5
    job_id = entry["job_id"]
    prefix = prefix_of(setting, entry["stem"], entry["rep"])
    cache = cache_path(setting, entry["stem"])
    pi = BP.setup_instance(str(REPO / entry["instance"]))
    headline = load_qubo_headline_from_h5(cache)
    cache_meta = headline.get("metadata") or {}
    cache_extra = cache_meta.get("extra") or {}   # what prepare() added
    shell = QUBOModule.QUBO()
    shell.Q = {}
    shell.n_vars = headline["n_vars"]
    shell.constant = headline["constant"]
    model = QUBOModule.TimeAllocationQUBO.from_cache(pi, shell, load_x_index_from_h5(cache))

    prefix.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{prefix}_veloxq_job_id_phase2.txt").write_text(f"{job_id}\n", encoding="utf-8")
    samples = QUBOModule.save_sampleset(response, f"{prefix}_veloxq_samples_phase2.npz")
    job.save_result(f"{prefix}_veloxq_result_phase2.h5")
    raw = gzip_in_place(Path(f"{prefix}_veloxq_result_phase2.h5"))

    best = response.first
    vartype = response.vartype.name
    sample = dict(best.sample)
    if vartype == "SPIN":
        state = QUBOModule._spins_to_binary(sample, shell.n_vars)
    else:
        state = [int(sample.get(i, sample.get(str(i), 0))) for i in range(shell.n_vars)]
    energy = float(qubo_energy_from_h5(str(cache), state))
    L = model.decode(state)
    best_state = BP._save_state(f"{prefix}_veloxq_best_state_phase2.npz", state, energy)
    info = dict(getattr(response, "info", {}) or {})
    solver_time = info.get("total_time")
    config = cache_meta.get("config")
    metadata: Dict[str, Any] = {
        "solver": f"QUBO/VeloxQ ({entry['backend']})",
        "stages_solved": ["phase2"],
        "phase2": {
            "build_time_seconds": cache_extra.get("build_time_seconds"),
            "upload_seconds": entry.get("upload_seconds"),
            "veloxq_solver_time_seconds": round(float(solver_time), 3) if solver_time is not None else None,
            "veloxq_effective_mode": "submit (batch: submitted without waiting, pulled later)",
            "veloxq_job_id": job_id,
            "submitted_at": entry.get("submitted_at"),
            "pulled_at": pulled_at,
            "veloxq_job_statistics": plain(getattr(job, "statistics", None)),
            "veloxq_job_timeline": plain(getattr(job, "timeline", None)),
            "veloxq_samples_file": samples,
            "veloxq_raw_result_file": raw,
            "best_state_file": best_state,
            "veloxq_vartype": vartype,
            "veloxq_response_info": run_record.json_safe(info),
            "veloxq_sent_as": "Ising h5 written from the cache arrays, float64",
            "uploaded_ising_h5": entry.get("ising_h5"),
            "n_vars": shell.n_vars,
            "n_q_entries": cache_meta.get("n_q_entries"),
            "energy": round(energy, 3),
            "lessons_planned": len(L),
            "qubo_matrix": BP._cached_qubo_matrix_stats(str(cache)),
            "qubo_config": run_record.json_safe(config),
            "rules": run_record.rule_manifest(qubo_config=config),
            "qubo_room_presolve": cache_extra.get("room_presolve_stats"),
            "qubo_penalty_requirements": cache_extra.get("penalty_requirements"),
            "qubo_penalty_profile_set_penalties": cache_extra.get("penalty_profile_set_penalties"),
            "qubo_cache_code_version": cache_extra.get("code_version"),
            "qubo_cache": str(cache),
            "qubo_cache_file": run_record.file_identity(cache),
        },
        "phase3": {},
        "veloxq": {"backend": entry["backend"], "num_rep": entry["num_rep"], "num_steps": entry["num_steps"],
                   "mode": "submit (batch)", "problem": entry.get("problem"), "file_id": entry.get("file_id")},
        "setting": {"name": setting, "description": SCENARIOS[setting][0], "overrides": SCENARIOS[setting][1],
                    "repetition": entry["rep"]},
        "submission_code": entry.get("code"),
        "environment": BP._collect_environment_metadata(),
        "instance": BP._collect_instance_metadata(pi),
    }
    BP._save_and_verify(pi, L, {}, metadata, out_path=str(solution_path(entry)), verify=True, pr5=True)
    print(f"[{setting}] {entry['stem']} rep {entry['rep']}: energy {energy:.1f}, |L| {len(L)}, "
          f"solver time {solver_time} s")
    return 0


def status(setting: str) -> None:
    from veloxq_sdk import Job
    entries = read_jsonl(setting_dir(setting) / "jobs.jsonl")
    tally: Dict[str, int] = {}
    for e in entries:
        state = "saved" if solution_path(e).exists() else job_status(_retry(
            f"status of {e['job_id']}", lambda: Job.from_id(e["job_id"])))
        tally[state] = tally.get(state, 0) + 1
    print(f"[{setting}] {len(entries)} jobs: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["prepare", "submit", "pull", "status", "run", "_process"])
    ap.add_argument("--settings", nargs="+", choices=sorted(SCENARIOS))
    ap.add_argument("--setting", choices=sorted(SCENARIOS), help="(_process) the job's setting")
    ap.add_argument("--job-id", help="(_process) the job to process")
    ap.add_argument("--reps", type=int, help="VeloxQ calls per instance (required to submit)")
    ap.add_argument("--num-steps", type=int, help="VeloxQ num_steps (required to submit)")
    ap.add_argument("--num-rep", type=int, help="VeloxQ num_rep (required to submit)")
    ap.add_argument("--backend", default="h100-1", choices=["h100-1", "h100-2", "plgrid"])
    ap.add_argument("--wait", type=float, default=None,
                    help="(pull, run) seconds between pulls until no job is pending or running")
    ap.add_argument("--tiers", nargs="*")
    ap.add_argument("--only", nargs="*", help="instance names")
    ap.add_argument("--instance-files", nargs="+", type=Path,
                    help="instance files instead of the synthetic suite (certified entries of the registry)")
    ap.add_argument("--out-name", default="veloxq",
                    help="outputs in artifacts/campaign/<out-name>/<setting>/ (default: veloxq)")
    ap.add_argument("--allow-uncommitted", action="store_true", help="(smoke tests only)")
    args = ap.parse_args()

    global OUT_ROOT
    OUT_ROOT = REPO / "artifacts" / "campaign" / args.out_name
    if args.command == "_process":
        return process(args.setting, args.job_id)
    if not args.settings:
        ap.error("--settings is required")
    if args.instance_files:
        if args.out_name == "veloxq":
            ap.error("--instance-files needs its own --out-name (artifacts/campaign/veloxq holds the synthetic suite)")
        files = [p if p.is_absolute() else REPO / p for p in args.instance_files]
        missing = [str(p) for p in files if not p.is_file()]
        if missing:
            raise SystemExit("no such instance file: " + ", ".join(missing))
    else:
        files = instances(INSTANCES, args.tiers, args.only)
    if not files:
        raise SystemExit("no instance selected")
    if args.command in ("submit", "run"):
        if None in (args.reps, args.num_steps, args.num_rep):
            ap.error("--reps, --num-steps and --num-rep are required (no defaults: each experiment sets them)")
        check_registry(files)
        dirty = uncommitted_code()
        if dirty and not args.allow_uncommitted:
            raise SystemExit("uncommitted changes in the code the runs use: " + ", ".join(dirty))
    for setting in args.settings:
        if args.command in ("prepare", "run"):
            prepare(setting, files)
        if args.command in ("submit", "run"):
            print(f"[{setting}] submitting: {len(files)} instances x {args.reps} calls, num_steps "
                  f"{args.num_steps}, num_rep {args.num_rep}, backend {args.backend} ({now()})", flush=True)
            submit(setting, files, args)
        if args.command in ("pull", "run"):
            pull(setting, args.wait)
        if args.command == "status":
            status(setting)
    return 0


if __name__ == "__main__":
    sys.exit(main())
