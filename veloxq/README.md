# VeloxQ on the synthetic suite: penalty settings

**Settings in this folder: S0, S1, S2, S3, S4, S5, S6.** All planned settings are here. The repair of the S3 answers is in `repair/` (*Repair of the S3 answers*, at the end).

The raw campaign outputs (the setting folders and `analysis/`) are published at https://github.com/janfifian/VeloxQ_runs_results, in its folder `veloxq/`; this folder adds this README, `SHA256SUMS`, `.gitattributes`, `logs/` and `scripts/`, which can be copied into `veloxq/` there.

## What was run

The time-allocation stage (phase 2) of every certified synthetic instance (`../instances/synthetic`), compiled to a QUBO under each penalty setting and solved by VeloxQ:

- VeloxQ backend `h100-1`, `num_steps` 10000, `num_rep` 4096 (replicas, each returned as a sample); 3 independent calls per instance and setting. The SDK (`veloxq_sdk` 0.1.dev125+ge290bd081) takes no seed, so the calls are independent but cannot be replayed;
- the jobs of a setting were submitted together and their results pulled when they finished; each call's timetable is decoded from its lowest-energy sample (the solver's answer), with no repair;
- rules: every hard rule of the paper, room rows on 15-minute cells, the 15-minute break and PR5 (no synthetic instance has online lessons, so PR5 is empty there);
- code: tag `campaign-2026-10-qubo` (commit bd8a847); decoding and checks on Windows-11-10.0.26200-SP0, Gurobi 12.0.3 for the exact room assignment.

| setting | what it is | overrides of the configured encoding |
|---|---|---|
| S0 | as configured | none (the configured encoding) |
| S1 | presolve (implied) + room-count coefficient 100 | `room_presolve` = "implied", `Lambda_room_count` = 100.0 |
| S2 | presolve (counts) + penalties raised to 1.5 x requirement | `room_presolve` = "counts", `penalty_profile` = "raised", `penalty_margin` = 1.5 |
| S3 | presolve (counts) + sufficient penalties (margin 1.5) | `room_presolve` = "counts", `penalty_profile` = "sufficient", `penalty_margin` = 1.5 |
| S4 | all rows + sufficient penalties (margin 1.5), seat rows base | `penalty_profile` = "sufficient", `penalty_margin` = 1.5, `penalty_profile_keep` = ["Lambda_room_capacity"] |
| S5 | presolve (counts), base penalties | `room_presolve` = "counts" |
| S6 | presolve (counts) + sufficient penalties (margin 5) | `room_presolve` = "counts", `penalty_profile` = "sufficient", `penalty_margin` = 5.0 |

## Files

One folder per setting (`<stem>` is the instance file name without `.yaml`, `<r>` the call, 1 to 3):

| file | content |
|---|---|
| `setting.json` | the setting and its overrides |
| `jobs.jsonl` | one line per submitted job: job id, submission time, upload and submission seconds, the hash of the uploaded Ising file and of the QUBO file, the code commit |
| `caches/<stem>.qubo_cache.h5` | the QUBO as submitted: matrix, variable index, configuration, the room presolve's row counts and what each penalty had to exceed on the instance |
| `rep_<r>/<stem>_velox_solution.yaml` | the timetable decoded from the lowest-energy sample, with the verifier's verdicts (and a room for each lesson when an exact room assignment exists) and the run record: code version, solver and library versions, job id, submission and pull times, VeloxQ's job statistics and timeline, matrix size and coefficient range, penalty requirements, instance sha256 |
| `rep_<r>/<stem>_veloxq_samples_phase2.npz` | every sample VeloxQ returned: states packed eight variables per byte (in the order of `labels`), energies and occurrence counts as reported, vartype, solver info |
| `rep_<r>/<stem>_veloxq_result_phase2.h5.gz` | the server's result file, gzipped (the record gives the sha256 of the uncompressed file) |
| `rep_<r>/<stem>_veloxq_best_state_phase2.npz` | the lowest-energy sample whole (decision and auxiliary bits, in the QUBO's variable order) with its energy on the matrix |
| `rep_<r>/<stem>_veloxq_job_id_phase2.txt`, `rep_<r>/<stem>.log` | the job id; the processing log |

`logs/` holds the campaign's console transcripts and logs, `scripts/` the scripts (see *How to check*). `analysis/` holds the tables of the analysis of these files: per call (`calls.csv`), per setting and tier (`tiers.csv`), the settings per instance (`paired.csv`), the 16 lowest-energy samples of each call decoded and checked (`topk.csv`), how the lowest-energy sample and the sample with the fewest violations among the 16 break, rule by rule (`breakdown.csv`, per tier `breakdown_tiers.csv`), the settings side by side per tier (`tier_view.csv`); and, from `scripts/check_energy_separation.py`, where each call's samples lie relative to the best legal timetable, the MILP optimum (`energy_separation.csv`), and every timetable one move from that optimum on five instances (`optimum_neighbours.csv`).

Each run record names its instance by the sha256 of the file's content (CRLF turned into LF); every one of them is the registry entry of a file in `../instances/synthetic`, which the assembly script checks. `SHA256SUMS` lists every file here: binary files by their bytes, text files (`.yaml`, `.jsonl`, `.json`, `.csv`, `.log`, `.txt`, `.md`, `.py`) by their content with Windows line ends turned into Unix ones, because git may store them with either. `sha256sum -c SHA256SUMS` holds on a checkout with Unix line ends; `scripts/verify_veloxq_deposit.py` holds on either. Every hash inside the run records is of a binary file or independent of line ends.

## How to check

**Without the project's code** (Python 3 with numpy, h5py and PyYAML), from this folder:

    python scripts/verify_veloxq_deposit.py

It checks every file against `SHA256SUMS`; every call's files against its run record (job id; hashes of the samples, of the server file, also decompressed, and of the best state; the QUBO file submitted and decoded); every call's energies on its deposited QUBO file (the best state has the recorded energy, it is the sample VeloxQ reported lowest, and the energy VeloxQ reported is that sample's energy on the matrix in spin form); and the verdicts in the records against `analysis/calls.csv` and `analysis/tier_view.csv`. With `repair/`, also every repair call's files and links, and the repair tables recomputed from the records (*Repair of the S3 answers*, below).

**The analysis**, from a checkout of the project at the tag `campaign-2026-10-qubo` (it needs the project's decoder and verifier, and Gurobi for the exact room assignment; copy `scripts/analyze_veloxq_campaign.py` into the checkout's `scripts/` if it is not there):

    python scripts/analyze_veloxq_campaign.py --root repository_ready/veloxq_synthetic --out <folder> --top-k 16
    python repository_ready/veloxq_synthetic/scripts/verify_veloxq_deposit.py --compare-analysis <folder>

The first command recomputes the analysis tables in `analysis/` from the files here (the timetables decoded from the samples, the verifier's checks, the deletion of surplus lessons, the weighted MILP objective); the second compares them with the deposited tables cell by cell. The energy check, which also needs the MILP optima (`../milp_synthetic_weighted`):

    python scripts/check_energy_separation.py --root repository_ready/veloxq_synthetic --milp repository_ready/milp_synthetic_weighted --out <folder> --neighbours easy_003_seed_1030 medium_005_seed_1050 medium_006_seed_1061 hard_008_seed_1084 hard_009_seed_1090

**How the runs were made** (these need the project's code): `scripts/veloxq_batch.py` (the QUBO files, the submission, and the processing of each result), `scripts/run_penalty_scenarios.py` (the settings, `SCENARIOS`), `scripts/assemble_veloxq_campaign_deposit.py` (this folder), `scripts/make_figures.py` (the paper's tables, from `analysis/`).

Verdicts: *V* = the number of violated hard constraints of the time stage (course hours, lesson blocks, overlaps of a lecturer or a group, availability, assigned lecturer) and of the room rows on 15-minute cells; *all checks* = V = 0, an exact assignment of rooms to the in-person lessons, the 15-minute break and PR5.

## Calls not entirely at the tag

- S0, `easy_000_seed_1000`: its QUBO file was built at commit 9d7c076, which differs from the tag only in `scripts/veloxq_batch.py`.
- S0, `easy_000_seed_1000`: call 1 was submitted at commit 9d7c076, which differs from the tag only in `scripts/veloxq_batch.py`.

## Results

Lowest-energy sample of each call, before any repair. *Instances*: instances with V = 0 in at least one of their calls; *solver*: VeloxQ's reported solver time per call, seconds (median).

| setting | tier | calls | calls with V = 0 | calls passing all checks | instances (V = 0 in some call) | median V | median solver |
|---|---|---:|---:|---:|---:|---:|---:|
| S0 | easy | 60 | 43 | 43 | 20 of 20 | 0.0 | 4.3 |
| S0 | medium | 45 | 14 | 14 | 10 of 15 | 1.0 | 10.7 |
| S0 | hard | 60 | 3 | 3 | 2 of 20 | 5.5 | 18.8 |
| S0 | extreme | 27 | 0 | 0 | 0 of 9 | 47.0 | 35.1 |
| S1 | easy | 60 | 33 | 33 | 15 of 20 | 0.0 | 2.8 |
| S1 | medium | 45 | 19 | 18 | 10 of 15 | 1.0 | 8.9 |
| S1 | hard | 60 | 3 | 2 | 3 of 20 | 5.5 | 15.9 |
| S1 | extreme | 27 | 0 | 0 | 0 of 9 | 50.0 | 30.6 |
| S2 | easy | 60 | 37 | 37 | 18 of 20 | 0.0 | 2.7 |
| S2 | medium | 45 | 8 | 8 | 7 of 15 | 2.0 | 7.2 |
| S2 | hard | 60 | 3 | 3 | 3 of 20 | 4.0 | 13.1 |
| S2 | extreme | 27 | 0 | 0 | 0 of 9 | 36.0 | 26.9 |
| S3 | easy | 60 | 60 | 60 | 20 of 20 | 0.0 | 2.6 |
| S3 | medium | 45 | 38 | 38 | 15 of 15 | 0.0 | 7.2 |
| S3 | hard | 60 | 1 | 1 | 1 of 20 | 12.0 | 13.1 |
| S3 | extreme | 27 | 0 | 0 | 0 of 9 | 11.0 | 26.1 |
| S4 | easy | 60 | 22 | 22 | 10 of 20 | 2.0 | 4.4 |
| S4 | medium | 45 | 0 | 0 | 0 of 15 | 41.0 | 10.7 |
| S4 | hard | 60 | 0 | 0 | 0 of 20 | 69.0 | 18.9 |
| S4 | extreme | 27 | 0 | 0 | 0 of 9 | 97.0 | 35.1 |
| S5 | easy | 60 | 23 | 23 | 13 of 20 | 1.0 | 2.8 |
| S5 | medium | 45 | 4 | 4 | 3 of 15 | 3.0 | 7.2 |
| S5 | hard | 60 | 0 | 0 | 0 of 20 | 8.0 | 13.1 |
| S5 | extreme | 27 | 0 | 0 | 0 of 9 | 55.0 | 26.2 |
| S6 | easy | 60 | 60 | 60 | 20 of 20 | 0.0 | 2.7 |
| S6 | medium | 45 | 35 | 35 | 14 of 15 | 0.0 | 7.3 |
| S6 | hard | 60 | 2 | 2 | 2 of 20 | 12.0 | 13.1 |
| S6 | extreme | 27 | 0 | 0 | 0 of 9 | 11.0 | 26.2 |

## Repair of the S3 answers

The repair of the paper (H1, then H2 with k = 1 and 2 and 10 candidate places per item, repeated until a full pass changes nothing, with no limit on time or passes) on the answer of every S3 call, with the room rows of the MILP in the first key of its cost (`--room-set-rows`: per 15-minute cell where a candidate slot starts and per room set, the lessons whose free admissible rooms lie inside the set fit in it in number and in seats, and the lessons that can use a clean room fit in the clean rooms); and the continuation of the calls it leaves invalid with the targeted moves at k = 3. Each call runs `scripts/run_local_search.py` on the call's QUBO file (the first key: violations of the time stage, 15-minute-break and PR5 pairs, exceeded room rows of the MILP; the second: the weighted MILP objective), then the verifier with the exact room assignment. The commands (`scripts/run_veloxq_ls_campaign.py`):

    python scripts/run_veloxq_ls_campaign.py --settings S3 --output-name S3_room_set_rows --ks 1 2 --candidate-shortlist-k 10 --max-outer-passes none --max-wall-seconds-per-pass none --extra --room-set-rows

    python scripts/run_veloxq_ls_campaign.py --settings S3 --input-run S3_room_set_rows --output-name S3_room_set_rows_k3_targeted --calls-file stuck_calls.txt --ks 3 --candidate-shortlist-k 10 --max-outer-passes none --max-wall-seconds-per-pass none --extra --room-set-rows --targeted-k-opt-only

`S3_room_set_rows` ran in two batches with the same options: first the calls listed in `rerun_calls.txt` (those left without a room assignment by a repair without the room-set rows, which is not deposited), then the others.

Code: the commit each call ran at, from its run record.
- `S3_room_set_rows`: 2ebf72e (141 calls), 539da11 (51 calls).
- `S3_room_set_rows_k3_targeted`: 84b7eea (4 calls).
- 2ebf72e differs from 84b7eea only in `checks/README.md`, `checks/two_move_neighbourhood.py`, `paper/RECENZJA.md`, `scripts/run_veloxq_ls_campaign.py`.
- 539da11 differs from 84b7eea only in `checks/README.md`, `checks/two_move_neighbourhood.py`, `paper/RECENZJA.md`, `scripts/run_veloxq_ls_campaign.py`.
- In the code the repair uses, 84b7eea differs from the tag `campaign-2026-10-qubo` in `scripts/run_local_search.py`, `scripts/run_veloxq_ls_campaign.py`, `src/etpmachine/ETPMachine_LocalSearch.py`, `src/etpmachine/ETPMachine_Schedule.py`: the room-set rows of the repair and the driver's options.
- The records mark the checkout as modified; the files they list (`notebooks/velox_vs_gurobi_comparison.ipynb`, `scripts/LATO_instructions.txt`) are not used by the runs.

Files, in `repair/<run>/` (`<stem>` the instance, `<r>` the call):

| file | content |
|---|---|
| `settings.json` | the run's options (of its last invocation) and, for a continuation, the run it continues |
| `calls.json`, `summary.csv` | seconds per call (repair and verification); one line per call: the cost before and after, the verifier's statuses, the search's seconds and cycles |
| `rep_<r>/<stem>_postLS.yaml` | the repaired timetable with its run record: input timetable and instance (path and content hash), the cost's definition, the cost and its parts before and after, code version, command-line arguments |
| `rep_<r>/<stem>_postLS_verdict.json` | the verifier's verdict on it: every check, and the exact room assignment (a room for every in-person lesson when one exists) |
| `rep_<r>/<stem>_stats.json` | every cycle of the repair: the cost and the violations by rule before and after, seconds |
| `rep_<r>/<stem>_log.txt`, `rep_<r>/<stem>.log` | the repair's log; the process log (repair and verification) |
| `S3_room_set_rows/two_move_neighbourhood.json` | `checks/two_move_neighbourhood.py` on the calls the repair leaves invalid: for the course short of its minutes, what blocks each of its places, and how many moves of the missing lesson with at most one other lesson (every such move, not only the repair's 10 candidates) give a valid timetable |
| `S3_room_set_rows/rerun_calls.txt`, `S3_room_set_rows_k3_targeted/stuck_calls.txt` | the calls of the first batch; the calls continued |

`logs/veloxq_ls_room_sets_run.log` is the console of `S3_room_set_rows`. The tables in `analysis/` (`scripts/analyze_veloxq_repair.py`; PyYAML only): per call (`repair_calls.csv`), per tier (`repair_tiers.csv`), the calls left invalid (`repair_stuck.csv`). The weighted objective is given only for timetables that pass every check, with its gap to the proven optimum of the weighted MILP (`E_opt` of `analysis/energy_separation.csv`).

| tier | calls valid | instances valid | at the MILP optimum | gap median (max), % | best call per instance, median (max), % | search seconds median (max) |
|---|---:|---:|---:|---:|---:|---:|
| easy | 60 / 60 | 20 / 20 | 55 / 60 | 0.0 (1.6) | 0.0 (0.0) | 1.3 (5.8) |
| medium | 45 / 45 | 15 / 15 | 1 / 45 | 5.8 (13.9) | 4.2 (9.9) | 21.2 (46.1) |
| hard | 60 / 60 | 20 / 20 | 0 / 36 | 15.9 (44.0) | 12.4 (27.2) | 80.1 (174.1) |
| extreme | 23 / 27 | 9 / 9 | -- | -- | -- | 124.5 (284.5) |

Calls left invalid (`repair_stuck.csv`): the course short of its minutes, its places by the number of lessons in the way (`clashing lessons: places`), the valid moves of at most two lessons, and the continuation at k = 3:

| call | course | groups / students | places by clashing lessons | valid moves of 1 / 2 lessons | continued: valid |
|---|---:|---|---|---:|---|
| `extreme_014_seed_1140` call 1 | 34 (45 min missing) | 8 / 122 | 1:5 2:8 3:2 4:4 5:1 | 0 / 0 | True |
| `extreme_014_seed_1140` call 3 | 36 (45 min missing) | 10 / 189 | 1:5 2:8 3:7 4:5 | 0 / 0 | False |
| `extreme_014_seed_1142` call 3 | 47 (45 min missing) | 12 / 250 | 1:6 2:4 3:6 4:3 5:1 | 0 / 0 | False |
| `extreme_014_seed_1143` call 3 | 47 (45 min missing) | 9 / 164 | 1:4 2:4 3:5 4:2 | 0 / 0 | False |

To check: `scripts/verify_veloxq_deposit.py` (*How to check*, above) checks every repair call's files and links (input timetable, instance and verdict by content hash) and recomputes the three tables from the records. The exhaustive check of the calls left invalid needs the project's code:

    python checks/two_move_neighbourhood.py --run repository_ready/veloxq_synthetic/repair/S3_room_set_rows --caches repository_ready/veloxq_synthetic

