# 3_studies: cold MILP under the current rules (12 h of search)

The time-allocation MILP of the production instance `3_studies` with the weighted objective, from a
cold start, under the rules of the verifier (room rows on every 15-minute cell, the 15-minute break,
PR5, the per-course room filter): Gurobi 12.0.3, 14 threads, MIPGap 0, Gurobi's default seed and a
time limit of 12 h, run with `scripts/run_milp_campaign.py` at commit 8acb11f (`CAMPAIGN.json`). It
searched to the limit (Section 7.3 of the paper, Fig. 3): best objective -8,755 after 3 h 40 min of
search, bound -13,273, gap 51.6 %. The best incumbent was kept every 30 min and at 5,067 s, 5,476 s
and 7,081 s of the search (the times of the QUBO route under S3); the first incumbent and every kept
timetable pass every check of the verifier.

## Files

| file | content |
|---|---|
| `production/3_studies_instance_MIP_snapshot_<t>s.sol` | Gurobi's best solution at mark `t` (seconds of search), every variable; marks with the same incumbent share the file of the first |
| `production/3_studies_instance_MIP_first_incumbent.sol` | the first incumbent, 22.6 s into the search |
| `production/3_studies_instance_MIP_phase2.sol` | Gurobi's best solution at the time limit |
| `production/3_studies_instance_MIP_incumbents.jsonl` | every incumbent as found: time, objective, bound, work |
| `production/snapshots_20261128.json` | per kept solution: the marks it holds, incumbent, objective, lessons, the verifier's verdict, the objective's terms (`scripts/collect_milp_snapshots.py`, from the run's own decoding and checks) |
| `production/run_times_20261128.json` | start of the run, start of the search |
| `production/3_studies_instance_MIP_phase2_gurobi.log` | Gurobi's log of the search |
| `summary.csv`, `calls.json` | the driver's summary (status, objective, bound, gap, times, the verdicts on the first and the final timetable) and the run's wall time |
| `objective_vs_time.{pdf,png,csv}` | the best valid timetable over time against the QUBO route under S3 and S0 (`../veloxq_3studies`), and its points |
| `CAMPAIGN.json`, `console.txt` | the driver's settings and environment; the run's console |
| `production/3_studies_instance_MIP_solution.yaml` | the final timetable with the run record (solver settings, every incumbent, every mark) and the verifier's verdict (pseudonymised) |
| `production/..._first_incumbent_solution.yaml`, `..._snapshot_<t>s_solution.yaml` | the first incumbent and every kept one, decoded, with the verifier's verdict (pseudonymised) |
| `production/3_studies_instance.log` | the pipeline's log: the build, Gurobi's console, the decoding and the checks (pseudonymised; Gurobi's licence number removed) |

Pseudonymised: the decoded timetables and the pipeline's log name the real lecturers and courses of the
instance, so they are here pseudonymised with the map of the pseudonymised instance
(`../instances/3_studies/3_studies_instance.yaml`; `scripts/pseudonymise_3studies.py`); nothing else in
them changes. The run records inside them keep the hashes of the original files and of the original
instance, which the copies do not match; `SHA256SUMS` lists the copies by their bytes. The `.sol` files
decode against the instance, the pseudonymised one included (`scripts/recover_milp_snapshots.py`).
Every text file here has Unix line ends, and
`.gitattributes` stops git from converting them; `SHA256SUMS` lists every file by its bytes
(`sha256sum -c SHA256SUMS`). Rebuilt by `scripts/assemble_milp_3studies_deposit.py`.
