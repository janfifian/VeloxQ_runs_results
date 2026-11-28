# 3_studies: VeloxQ under S3 and S0, and the repair of the answers

VeloxQ on the production instance `3_studies`: five calls under setting S3 (19.10.2026) and five under S0 (28-29.10.2026), each on backend h100-1 with 10,000 steps and 4,096 replicas, made by `scripts/veloxq_batch.py`; then the repair of every answer by `scripts/run_veloxq_ls_campaign.py` (H1, then k-OPT moves with k = 1 and 2, a shortlist of 10, no cap on passes or time, the MILP's room-set rows counted in its cost) and, under S3, the same repair from an empty timetable. Both settings and the repairs are in Section 7.3 of the paper; S0 is the same run as S3 with the encoding as configured.

| setting | matrix | variables | entries | calls at | repair at |
|---|---|---|---|---|---|
| S3 | room_presolve counts, penalty_profile sufficient, penalty_margin 1.5 (base `cfg/qubo_cfg.yaml`) | 65,102 | 26,569,074 | 8783d1b | 2fa811c |
| S0 | as configured (base `cfg/qubo_cfg.yaml`) | 119,876 | 30,177,622 | 1ccf3d4 | 1ccf3d4 |

S0 ran at commit 1ccf3d4, whose code is that of the S3 run in every path the two drivers use, except five files changed since the S3 run in parts this run does not execute (checked by `run_veloxq_3studies_s0.py`, which launched it; its console is in `logs/`).

## The answers (the lowest-energy sample of each call)

`energy` is the sample's energy on the matrix, as its record and `summary.csv` give it; `violations` is the verifier's count over its rules; `by rule` lists those rules and, counted apart, the 15-minute break (`BREAK_*`) and PR5. No answer passes every check.

| setting | call | job id | solver (s) | energy | lessons | violations | by rule |
|---|---|---|---|---|---|---|---|
| S3 | 1 | `0d7aebf2-05f6-4f6d-ac3b-f4a0ccdc2b77` | 5,067 | 14,497,088.5 | 258 | 198 | `PR1_course_minutes` 76, `MC_max_chunks` 100, `PR3_PR4_lecturer_overlap` 1, `PR3_PR4_group_overlap` 21, `BREAK_lecturer` 4, `BREAK_group` 12, `PR5_mixed_modality` 12 |
| S3 | 2 | `320790fc-b38b-4b31-9935-73615ec8842a` | 5,066 | 16,118,130.5 | 239 | 196 | `PR1_course_minutes` 79, `MC_max_chunks` 87, `PR3_PR4_lecturer_overlap` 5, `PR3_PR4_group_overlap` 25, `BREAK_lecturer` 2, `BREAK_group` 7, `PR5_mixed_modality` 1 |
| S3 | 3 | `d8892b33-c69c-4334-9313-41a8e89ac273` | 5,067 | 16,003,734.5 | 237 | 192 | `PR1_course_minutes` 84, `MC_max_chunks` 87, `PR3_PR4_lecturer_overlap` 2, `PR3_PR4_group_overlap` 18, `CONJ_PHASE3_room_count` 1, `BREAK_lecturer` 1, `BREAK_group` 10, `PR5_mixed_modality` 6 |
| S3 | 4 | `208cce0f-f566-42ba-970e-ceb0b88cb333` | 5,066 | 15,473,343.0 | 246 | 196 | `PR1_course_minutes` 74, `MC_max_chunks` 95, `PR3_PR4_lecturer_overlap` 2, `PR3_PR4_group_overlap` 25, `BREAK_group` 14, `PR5_mixed_modality` 8 |
| S3 | 5 | `14c4897b-1ddf-4326-ac90-ed4edbf9348a` | 5,067 | 14,672,055.0 | 249 | 192 | `PR1_course_minutes` 83, `MC_max_chunks` 92, `PR3_PR4_lecturer_overlap` 3, `PR3_PR4_group_overlap` 14, `BREAK_group` 5, `PR5_mixed_modality` 8 |
| S0 | 1 | `1c71180f-6848-426b-8efe-455961807b6f` | 5,515 | 3,463,082,210.0 | 117 | 216 | `PR1_course_minutes` 84, `MC_max_chunks` 50, `PR3_PR4_lecturer_overlap` 22, `PR3_PR4_group_overlap` 58, `CONJ_PHASE3_room_count` 2, `BREAK_lecturer` 7, `BREAK_group` 16, `PR5_mixed_modality` 8 |
| S0 | 2 | `3c5e9b3a-400f-4d8e-8dac-0b434627dd14` | 5,517 | 3,284,702,050.0 | 115 | 200 | `PR1_course_minutes` 84, `MC_max_chunks` 48, `PR3_PR4_lecturer_overlap` 20, `PR3_PR4_group_overlap` 48, `BREAK_lecturer` 1, `BREAK_group` 4, `PR5_mixed_modality` 1 |
| S0 | 3 | `d884cdec-5cca-4fc2-9e3c-e9da7e811197` | 5,518 | 3,378,343,765.0 | 118 | 193 | `PR1_course_minutes` 87, `MC_max_chunks` 49, `PR3_PR4_lecturer_overlap` 26, `PR3_PR4_group_overlap` 31, `BREAK_lecturer` 3, `BREAK_group` 7, `PR5_mixed_modality` 1 |
| S0 | 4 | `fdefe565-9e70-445f-8c91-9bd0984838e1` | 5,517 | 3,289,496,950.0 | 122 | 173 | `PR1_course_minutes` 87, `MC_max_chunks` 48, `PR3_PR4_lecturer_overlap` 13, `PR3_PR4_group_overlap` 25, `BREAK_lecturer` 7, `BREAK_group` 10, `PR5_mixed_modality` 2 |
| S0 | 5 | `b87de4fe-ed61-430b-aa76-f9193e26ac97` | 5,518 | 3,460,966,440.0 | 107 | 166 | `PR1_course_minutes` 92, `MC_max_chunks` 39, `PR3_PR4_lecturer_overlap` 14, `PR3_PR4_group_overlap` 21, `BREAK_lecturer` 5, `BREAK_group` 9 |

## The repair

Violations before and after the repair count the verifier's rules, the 15-minute break, PR5 and the MILP's room-set rows. The objective is given only for timetables that pass every check, the exact room assignment included.

| run | call | violations before | after | lessons | left | valid | objective | time (min) |
|---|---|---|---|---|---|---|---|---|
| S3_room_set_rows | 1 | 226 | 1 | 130 | `PR1_course_minutes` 1 | no | -- | 26.4 |
| S3_room_set_rows | 2 | 206 | 3 | 130 | `PR1_course_minutes` 2, `PR3_PR4_group_overlap` 1 | no | -- | 17.6 |
| S3_room_set_rows | 3 | 212 | 2 | 132 | `MC_max_chunks` 1, `PR3_PR4_group_overlap` 1 | no | -- | 25.3 |
| S3_room_set_rows | 4 | 218 | 0 | 130 | -- | yes | -7,935 | 26.8 |
| S3_room_set_rows | 5 | 205 | 5 | 136 | `MC_max_chunks` 4, `PR3_PR4_group_overlap` 1 | no | -- | 22.6 |
| S3_room_set_rows_empty_start | empty timetable | 130 | 0 | 130 | -- | yes | -8,220 | 29.3 |
| S0_room_set_rows | 1 | 251 | 2 | 134 | `MC_max_chunks` 2 | no | -- | 27.7 |
| S0_room_set_rows | 2 | 206 | 1 | 130 | `PR1_course_minutes` 1 | no | -- | 21.8 |
| S0_room_set_rows | 3 | 204 | 2 | 132 | `MC_max_chunks` 1, `PR3_PR4_group_overlap` 1 | no | -- | 26.0 |
| S0_room_set_rows | 4 | 192 | 0 | 130 | -- | yes | -8,130 | 21.2 |
| S0_room_set_rows | 5 | 180 | 1 | 133 | `MC_max_chunks` 1 | no | -- | 23.5 |

## Files

| file | content |
|---|---|
| `<setting>/setting.json` | the setting's overrides of the base configuration |
| `<setting>/jobs.jsonl` | one line per call: job id, times, budget, hashes of the uploaded file and of the matrix, code commit |
| `<setting>/caches/3_studies_instance.qubo_cache.h5` | the matrix as submitted, with the configuration and the penalty requirements in its metadata |
| `<setting>/rep_<r>/3_studies_instance_veloxq_samples_phase2.npz` | every sample VeloxQ returned: states packed eight variables per byte (in the order of `labels`), energies (spin form) and occurrence counts as reported, vartype, solver info |
| `<setting>/rep_<r>/3_studies_instance_veloxq_best_state_phase2.npz` | the lowest-energy sample whole (decision and auxiliary bits, in the QUBO's variable order) with its energy on the matrix |
| `<setting>/rep_<r>/3_studies_instance_veloxq_job_id_phase2.txt` | the job id |
| `<setting>/rep_<r>/3_studies_instance_velox_solution.yaml` | the answer: the timetable decoded from the lowest-energy sample, with its run record and the verifier's verdict (pseudonymised) |
| `<setting>/rep_<r>/3_studies_instance.log` | the call's processing log (pseudonymised) |
| `<setting>/records.json` | per call: the answer's run record and verdict (pseudonymised), the hash of the original timetable file and its number of lessons |
| `repair/<run>/settings.json`, `calls.json`, `summary.csv` | the repair's options, wall time per call, and one row per call |
| `repair/<run>/rep_<r>/3_studies_instance_stats.json`, `_log.txt`, `.log` | the repair's passes and moves, its log |
| `repair/S3_room_set_rows_empty_start/inputs/3_studies_instance_empty.yaml` | the empty timetable the empty start began from |
| `repair/<run>/rep_<r>/3_studies_instance_postLS.yaml`, `_postLS_verdict.json` | the repaired timetable with its run record, and the verifier's verdict on it (pseudonymised) |
| `repair/<run>/records.json` | per call: the repaired timetable's run record and verdict (pseudonymised), the hash of the original timetable file and its number of lessons |
| `logs/` | the consoles: `veloxq_3studies_run.log` (S3: the calls (19.10.2026)); `veloxq_3studies_ls_run.log` (S3: the repair of the answers and from an empty timetable (19.10.2026)); `veloxq_3studies_S0_console.txt` (S0: the calls and their repair (28-29.10.2026)) |

Pseudonymised: the timetables (the answers' `*_velox_solution.yaml`, the repaired `*_postLS.yaml`), the verdict files (`*_postLS_verdict.json`) and the calls' processing logs (`<setting>/rep_<r>/*.log`) name the real lecturers, courses and student groups of the instance, so they are here pseudonymised with the map of the pseudonymised instance (`../instances/3_studies/3_studies_instance.yaml`; `scripts/pseudonymise_3studies.py`): lecturers, courses and their codes, programmes, institutes, faculties other than FTIMS, buildings and rooms are replaced by tokens, and nothing else changes. The run records inside them and `records.json` keep the hashes of the original files and of the original instance, which the pseudonymised copies do not match; `SHA256SUMS` lists the copies by their bytes. `records.json` gives the records and verdicts without the two soft metrics kept per student group (`soft_metrics.gap_minutes_by_group`, `soft_metrics.days_per_group.by_group`); the verdict files have them, pseudonymised. VeloxQ's server files (`*_veloxq_result_phase2.h5.gz`) repeat the samples and are not kept; the records give their hashes. The samples decode against the matrix (its `x_index`) and the instance; the pseudonymised instance keeps the order of every list, so they decode against it too.

Every text file here has Unix line ends (the runs wrote them on Windows), and `.gitattributes` stops git from converting them. In the run records, `sha256_file_bytes` of a text file, like `bytes` next to it, describes the copy with Windows line ends the run wrote; `sha256` is of the file with Unix line ends. `SHA256SUMS` lists every other file here by its bytes (131 files; `sha256sum -c SHA256SUMS`). Rebuilt by `scripts/assemble_veloxq_3studies_deposit.py`, which checks every call and repair against its records and every file against the identifiers of the instance before copying or pseudonymising it.
