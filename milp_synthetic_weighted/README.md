# MILP on the synthetic suite: weighted objective

**Status: 64 of 64 instances finished**: 50 solved to a proven optimum, 5 stopped before a proof of optimality with the best timetable found (the hard tier), 9 stopped at the time limit with the best timetable found (the extreme tier). The campaign is complete.

## What was run

The time-allocation MILP (phase 2) of every certified synthetic instance (`../instances/synthetic`), solved from a cold start until Gurobi proved optimality or reached the time limit (5 runs without a limit were stopped before that, see below):

- objective: the sum, each with weight 1, of lecturer satisfaction, the groups' idle time, the groups' active days, time of day (lecture-before is off); with the configured coefficients (satisfaction 80/20/0, time of day -5/0/+10, one unit per active group-day and per idle minute) it is integer-valued;
- rules: every hard rule of the paper, room rows on 15-minute cells, the 15-minute break and PR5 (no synthetic instance has online lessons, so PR5 is empty there);
- Gurobi 12.0.3, MIPGap 0.0, 14 threads, Seed 0 (default), no time limit on the easy, medium and hard tiers; a limit of 1 h (3,600 s) per instance on the extreme tier; one process per instance;
- code: tag `campaign-2026-10` (commit 48dd555); machine: 12th Gen Intel(R) Core(TM) i9-12900H, 20 logical processors, Windows 11.

Sessions: `CAMPAIGN_session1.json` started 2026-10-12T07:08:43+02:00 (tiers: all; time limit: none); `CAMPAIGN_2026-10-31T01-24-34.json` started 2026-10-31T01:24:34+01:00 (tiers: extreme; time limit: 3,600 s per instance); `CAMPAIGN_2026-11-04T01-46-59.json` started 2026-11-04T01:46:59+01:00 (tiers: easy; time limit: none); `CAMPAIGN_2026-11-04T01-47-36.json` started 2026-11-04T01:47:36+01:00 (tiers: hard; time limit: none); `CAMPAIGN_2026-11-04T10-02-55.json` started 2026-11-04T10:02:55+01:00 (tiers: hard; time limit: none); `CAMPAIGN_2026-11-17T22-36-16.json` started 2026-11-17T22:36:16+01:00 (tiers: hard; time limit: none); `CAMPAIGN_2026-11-18T10-38-07.json` started 2026-11-18T10:38:07+01:00 (tiers: hard; time limit: none); `CAMPAIGN_2026-11-19T23-55-23.json` started 2026-11-19T23:55:23+01:00 (tiers: hard; time limit: none); `CAMPAIGN_2026-11-20T23-02-18.json` started 2026-11-20T23:02:18+01:00 (tiers: hard; time limit: none); `CAMPAIGN.json` started 2026-11-24T23:25:55+01:00 (tiers: hard; time limit: none).

## Files

One folder per tier; per instance (`<stem>` is the instance file name without `.yaml`):

| file | content |
|---|---|
| `<stem>_MIP_solution.yaml` | the final timetable: the proven optimum, or the best one found when the run stopped (each lesson: course, lecturer, day and time), a room for every in-person lesson from the verifier's exact room assignment (it shows that rooms can be given; the room stage is not optimised here), and the run record: code version, solver and library versions, settings, instance sha256, model fingerprint, every incumbent with its time and work, status, objective, bound and gap, build and solve times, the first incumbent, and the verifier's verdicts |
| `<stem>_MIP_first_incumbent_solution.yaml` | the first feasible solution Gurobi found, as a timetable with the verifier's verdicts |
| `<stem>_MIP_first_incumbent.sol`, `<stem>_MIP_phase2.sol` | the first and the final solution in Gurobi's format, every variable |
| `<stem>_MIP_phase2_gurobi.log` | Gurobi's log of the solve |
| `<stem>.log` | the console output of the run (Gurobi's licence number removed) |

Campaign records: `summary.csv` (one row per finished instance), `CAMPAIGN.json` (the latest session) and `CAMPAIGN_*.json` (the earlier ones): settings, environment and instance list of each session; `calls.json` (wall time of each run, process start to end; not recorded for `hard_010_seed_1100`, `hard_010_seed_1101`, `hard_010_seed_1102`, `hard_010_seed_1103` and `hard_010_seed_1104`); `console.txt` (the first session's console); `console_remaining.txt` (the console of the later sessions and of their checks, launched by `run_milp_remaining.py` in the repository's root folder).

In `summary.csv` (rewritten from the run records after the campaign by `scripts/run_milp_campaign.py --summarize-only`, which added the last three of these columns) the times are seconds into the solve, from the run record's list of incumbents with Gurobi's objective of each: `time_to_last_incumbent_s` is the list's last entry, which on 30 runs repeats the best objective at the end of the solve; `time_to_best_incumbent_s` is when the final objective was first reached (*best* in the table below); `qubo_ls_best_objective` is the best objective of a QUBO+LS timetable of the instance that passes every check (`../veloxq_synthetic`: VeloxQ's S3 answers after the local-search repair, its k = 3 continuation included), and `time_to_beat_qubo_ls_s` is when the MILP first had an incumbent with a lower objective; it is empty on the 21 instances whose QUBO+LS timetable has the MILP's final objective (every easy instance and `medium_004_seed_1041`). Only the first and the final incumbent were decoded and checked, and Gurobi's objective of a timetable can be above the verifier's score of it, so by the verifier's score either event may have come earlier.

Every text file here has Unix line ends (the runs wrote them on Windows), and `.gitattributes` stops git from converting them; `SHA256SUMS` lists every file by its bytes (`sha256sum -c SHA256SUMS`). Every hash a run record gives for a file here is that file's sha256, except `sha256_file_bytes` of a text file: that, like `bytes` next to it, describes the copy with Windows line ends the run wrote (`sha256` is of the file here). Each run record names its instance by the hash that `../instances/registry.csv` lists for its file in `../instances/synthetic`; the assembly script checks every one.

Verdicts: *time core* = course hours, lesson blocks, no overlaps of a lecturer or a group, availability, assigned lecturer; *room rows* = the room counts on every 15-minute cell; *rooms* = an exact assignment of rooms to the in-person lessons; *policy rules* = the 15-minute break and PR5; *all checks* = all four.

## Runs with a time limit

The 9 instances of the extreme tier ran with a limit of 1 h (3,600 s) per instance, from the same code on the same machine. All 9 stopped at the limit (Gurobi status TIME_LIMIT) with a timetable that passes every check; none has a proven optimum. Their gaps are 123.7-2,673.6 %; each found its final timetable between 580 s and 2,449 s into the solve, and its first feasible solution at most 6.5 s into it (every first solution passes every check as well). They are not optima, so the analyses that need the MILP optima (`../veloxq_synthetic/analysis/energy_separation.csv`) leave them out.

## Stopped before a proof

`hard_010_seed_1100` ran without a time limit, like the rest of its tier, and was stopped after 21.5 h of search (Gurobi status INTERRUPTED). Best objective -2,906, found after 9.9 h, with no better timetable in the remaining 11.6 h; bound -3,008, gap 3.5 %, 5,030,232 nodes. Its final timetable passes every check; its first feasible solution, found 0.010 s into the solve, passes every check. It is not an optimum, so the analyses that need the MILP optima (`../veloxq_synthetic/analysis/energy_separation.csv`) leave it out.

`hard_010_seed_1101` ran without a time limit, like the rest of its tier, and was stopped after 12.0 h of search (Gurobi status INTERRUPTED). Best objective -2,713, found after 8.8 h, with no better timetable in the remaining 3.2 h; bound -2,806, gap 3.4 %, 2,705,899 nodes. Its final timetable passes every check; its first feasible solution, found 0.026 s into the solve, passes every check. It is not an optimum, so the analyses that need the MILP optima (`../veloxq_synthetic/analysis/energy_separation.csv`) leave it out.

`hard_010_seed_1102` ran without a time limit, like the rest of its tier, and was stopped after 14.0 h of search (Gurobi status INTERRUPTED). Best objective -2,823, found after 1.3 h, with no better timetable in the remaining 12.7 h; bound -2,932, gap 3.9 %, 3,562,137 nodes. Its final timetable passes every check; its first feasible solution, found 0.088 s into the solve, passes every check. It is not an optimum, so the analyses that need the MILP optima (`../veloxq_synthetic/analysis/energy_separation.csv`) leave it out.

`hard_010_seed_1103` ran without a time limit, like the rest of its tier, and was stopped after 16.0 h of search (Gurobi status INTERRUPTED). Best objective -1,914, found after 0.9 h, with no better timetable in the remaining 15.1 h; bound -2,597, gap 35.7 %, 2,786,277 nodes. Its final timetable passes every check; its first feasible solution, found 0.080 s into the solve, passes every check. It is not an optimum, so the analyses that need the MILP optima (`../veloxq_synthetic/analysis/energy_separation.csv`) leave it out.

`hard_010_seed_1104` ran without a time limit, like the rest of its tier, and was stopped after 13.25 h of search (Gurobi status INTERRUPTED). Best objective -2,044, found after 2.3 h, with no better timetable in the remaining 10.9 h; bound -2,562, gap 25.3 %, 2,602,195 nodes. Its final timetable passes every check; its first feasible solution, found 0.105 s into the solve, passes every check. It is not an optimum, so the analyses that need the MILP optima (`../veloxq_synthetic/analysis/energy_separation.csv`) leave it out.

## Extreme tier: attempt to prove optimality

An experimental run on a different machine from the rest of this folder: 13th Gen Intel(R) Core(TM) i7-1365U, 12 logical processors, 12 threads, Gurobi 13.0.2, Python 3.14.0. It ran `extreme_011_seed_1110` without a time limit, to see whether an extreme instance can be solved to optimality, and was stopped after 62.6 h of search (Gurobi status INTERRUPTED); its files are in `extreme_no_limit/`. Best objective -863, found after 11.7 h, with no better timetable in the remaining 50.9 h; bound -2,651, gap 207 %, 1,899,068 nodes. Its timetable passes every check. Code, model and the other settings are those above (the model has the fingerprint of its run in `extreme/`), without the time limit. The same files per instance as above.

## Results

Times in seconds. *Build*: building the model; *solve*: Gurobi's run time, to the proof of optimality or until the run stopped; *best*: the time into the solve at which the final timetable was found; *first*: the time into the solve at which the first feasible solution was found.

| instance | status | objective | bound | gap | build | solve | best | first | first objective | first: verifier | final: verifier |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `easy_000_seed_1000` | OPTIMAL | -420 | -420 | 0.0 % | 0.17 | 0.1 | 0.042 | 0.006 | 369 | all checks | all checks |
| `easy_000_seed_1001` | OPTIMAL | -390 | -390 | 0.0 % | 0.17 | 0.1 | 0.028 | 0.000 | 429 | all checks | all checks |
| `easy_000_seed_1002` | OPTIMAL | -420 | -420 | 0.0 % | 0.17 | 0.1 | 0.038 | 0.000 | 34 | all checks | all checks |
| `easy_000_seed_1003` | OPTIMAL | -420 | -420 | 0.0 % | 0.16 | 0.1 | 0.076 | 0.009 | 324 | all checks | all checks |
| `easy_000_seed_1004` | OPTIMAL | -405 | -405 | 0.0 % | 0.16 | 0.1 | 0.037 | 0.001 | 99 | all checks | all checks |
| `easy_001_seed_1010` | OPTIMAL | -741 | -741 | 0.0 % | 0.20 | 0.3 | 0.240 | 0.002 | -212 | all checks | all checks |
| `easy_001_seed_1011` | OPTIMAL | -695 | -695 | 0.0 % | 0.21 | 0.2 | 0.177 | 0.003 | 123 | all checks | all checks |
| `easy_001_seed_1012` | OPTIMAL | -739 | -739 | 0.0 % | 0.21 | 0.2 | 0.157 | 0.030 | -312 | all checks | all checks |
| `easy_001_seed_1013` | OPTIMAL | -740 | -740 | 0.0 % | 0.21 | 0.2 | 0.200 | 0.028 | -274 | all checks | all checks |
| `easy_001_seed_1014` | OPTIMAL | -681 | -681 | 0.0 % | 0.12 | 0.2 | 0.100 | 0.002 | 413 | all checks | all checks |
| `easy_002_seed_1020` | OPTIMAL | -916 | -916 | 0.0 % | 0.13 | 0.3 | 0.306 | 0.031 | -40 | all checks | all checks |
| `easy_002_seed_1021` | OPTIMAL | -913 | -913 | 0.0 % | 0.14 | 0.1 | 0.131 | 0.004 | 549 | all checks | all checks |
| `easy_002_seed_1022` | OPTIMAL | -920 | -920 | 0.0 % | 0.15 | 0.2 | 0.218 | 0.008 | 510 | all checks | all checks |
| `easy_002_seed_1023` | OPTIMAL | -922 | -922 | 0.0 % | 0.14 | 0.2 | 0.140 | 0.000 | 549 | all checks | all checks |
| `easy_002_seed_1024` | OPTIMAL | -913 | -913 | 0.0 % | 0.14 | 0.2 | 0.222 | 0.000 | 379 | all checks | all checks |
| `easy_003_seed_1030` | OPTIMAL | -1,161 | -1,161 | 0.0 % | 0.18 | 0.3 | 0.237 | 0.002 | 57 | all checks | all checks |
| `easy_003_seed_1031` | OPTIMAL | -1,165 | -1,165 | 0.0 % | 0.18 | 0.3 | 0.269 | 0.002 | 138 | all checks | all checks |
| `easy_003_seed_1032` | OPTIMAL | -1,155 | -1,155 | 0.0 % | 0.17 | 0.3 | 0.223 | 0.032 | -84 | all checks | all checks |
| `easy_003_seed_1033` | OPTIMAL | -1,153 | -1,153 | 0.0 % | 0.18 | 0.3 | 0.270 | 0.002 | 90 | all checks | all checks |
| `easy_003_seed_1034` | OPTIMAL | -1,166 | -1,166 | 0.0 % | 0.17 | 0.3 | 0.299 | 0.000 | 475 | all checks | all checks |
| `medium_004_seed_1040` | OPTIMAL | -1,791 | -1,791 | 0.0 % | 0.22 | 0.7 | 0.708 | 0.015 | 723 | all checks | all checks |
| `medium_004_seed_1041` | OPTIMAL | -1,778 | -1,778 | 0.0 % | 0.23 | 0.6 | 0.562 | 0.000 | 2,461 | all checks | all checks |
| `medium_004_seed_1042` | OPTIMAL | -1,678 | -1,678 | 0.0 % | 0.22 | 0.8 | 0.675 | 0.003 | 1,430 | all checks | all checks |
| `medium_004_seed_1043` | OPTIMAL | -1,702 | -1,702 | 0.0 % | 0.22 | 0.6 | 0.537 | 0.000 | 2,386 | all checks | all checks |
| `medium_004_seed_1044` | OPTIMAL | -1,765 | -1,765 | 0.0 % | 0.21 | 0.8 | 0.614 | 0.005 | 953 | all checks | all checks |
| `medium_005_seed_1050` | OPTIMAL | -2,069 | -2,069 | 0.0 % | 0.27 | 1.3 | 1.176 | 0.000 | 1,854 | all checks | all checks |
| `medium_005_seed_1051` | OPTIMAL | -2,167 | -2,167 | 0.0 % | 0.28 | 1.2 | 1.154 | 0.016 | 3,361 | all checks | all checks |
| `medium_005_seed_1052` | OPTIMAL | -2,171 | -2,171 | 0.0 % | 0.27 | 1.1 | 0.927 | 0.000 | 2,470 | all checks | all checks |
| `medium_005_seed_1053` | OPTIMAL | -2,133 | -2,133 | 0.0 % | 0.27 | 1.1 | 1.084 | 0.048 | 1,572 | all checks | all checks |
| `medium_005_seed_1054` | OPTIMAL | -2,238 | -2,238 | 0.0 % | 0.27 | 0.7 | 0.606 | 0.007 | 2,798 | all checks | all checks |
| `medium_006_seed_1060` | OPTIMAL | -2,476 | -2,476 | 0.0 % | 0.30 | 1.0 | 0.928 | 0.004 | 1,812 | all checks | all checks |
| `medium_006_seed_1061` | OPTIMAL | -2,354 | -2,354 | 0.0 % | 0.30 | 2.6 | 2.295 | 0.012 | 4,412 | all checks | all checks |
| `medium_006_seed_1062` | OPTIMAL | -2,463 | -2,463 | 0.0 % | 0.30 | 1.4 | 1.290 | 0.004 | 2,487 | all checks | all checks |
| `medium_006_seed_1063` | OPTIMAL | -2,449 | -2,449 | 0.0 % | 0.30 | 2.2 | 2.142 | 0.002 | 3,167 | all checks | all checks |
| `medium_006_seed_1064` | OPTIMAL | -2,499 | -2,499 | 0.0 % | 0.29 | 0.9 | 0.771 | 0.003 | 3,907 | all checks | all checks |
| `hard_007_seed_1070` | OPTIMAL | -2,892 | -2,892 | 0.0 % | 0.34 | 3.4 | 3.179 | 0.005 | 3,731 | all checks | all checks |
| `hard_007_seed_1071` | OPTIMAL | -2,833 | -2,833 | 0.0 % | 0.35 | 7.4 | 5.665 | 0.059 | 296 | all checks | all checks |
| `hard_007_seed_1072` | OPTIMAL | -2,689 | -2,689 | 0.0 % | 0.35 | 6.6 | 4.419 | 0.005 | 5,018 | all checks | all checks |
| `hard_007_seed_1073` | OPTIMAL | -2,616 | -2,616 | 0.0 % | 0.36 | 7.5 | 3.625 | 0.005 | 4,911 | all checks | all checks |
| `hard_007_seed_1074` | OPTIMAL | -2,889 | -2,889 | 0.0 % | 0.35 | 3.6 | 2.111 | 0.000 | 6,652 | all checks | all checks |
| `hard_008_seed_1080` | OPTIMAL | -3,033 | -3,033 | 0.0 % | 0.41 | 74.2 | 65.485 | 0.000 | 8,850 | all checks | all checks |
| `hard_008_seed_1081` | OPTIMAL | -2,758 | -2,758 | 0.0 % | 0.41 | 1,089.5 | 1,026.046 | 0.002 | 11,896 | all checks | all checks |
| `hard_008_seed_1082` | OPTIMAL | -2,890 | -2,890 | 0.0 % | 0.40 | 58.1 | 56.401 | 0.013 | 4,774 | all checks | all checks |
| `hard_008_seed_1083` | OPTIMAL | -2,506 | -2,506 | 0.0 % | 0.41 | 12,199.6 | 10,800.997 | 0.014 | 10,500 | all checks | all checks |
| `hard_008_seed_1084` | OPTIMAL | -2,847 | -2,847 | 0.0 % | 1.10 | 1,828.2 | 1,567.574 | 0.152 | 1,575 | all checks | all checks |
| `hard_009_seed_1090` | OPTIMAL | -2,651 | -2,651 | 0.0 % | 1.20 | 24,546.6 | 4,687.804 | 0.014 | 9,588 | all checks | all checks |
| `hard_009_seed_1091` | OPTIMAL | -2,813 | -2,813 | 0.0 % | 0.46 | 11,994.6 | 10,090.191 | 0.007 | 10,122 | all checks | all checks |
| `hard_009_seed_1092` | OPTIMAL | -2,624 | -2,624 | 0.0 % | 0.47 | 6,899.7 | 6,425.750 | 0.009 | 15,351 | all checks | all checks |
| `hard_009_seed_1093` | OPTIMAL | -2,930 | -2,930 | 0.0 % | 0.45 | 3,330.5 | 2,207.072 | 0.097 | 6,132 | all checks | all checks |
| `hard_009_seed_1094` | OPTIMAL | -3,111 | -3,111 | 0.0 % | 0.46 | 100.3 | 90.229 | 0.009 | 10,309 | all checks | all checks |
| `hard_010_seed_1100` | INTERRUPTED | -2,906 | -3,008 | 3.5 % | 0.52 | 77,403.7 | 35,641.725 | 0.010 | 13,694 | all checks | all checks |
| `hard_010_seed_1101` | INTERRUPTED | -2,713 | -2,806 | 3.4 % | 1.45 | 43,204.5 | 31,707.758 | 0.026 | 15,099 | all checks | all checks |
| `hard_010_seed_1102` | INTERRUPTED | -2,823 | -2,932 | 3.9 % | 0.49 | 50,403.1 | 4,654.124 | 0.088 | 8,349 | all checks | all checks |
| `hard_010_seed_1103` | INTERRUPTED | -1,914 | -2,597 | 35.7 % | 0.49 | 57,604.4 | 3,083.574 | 0.080 | 3,744 | all checks | all checks |
| `hard_010_seed_1104` | INTERRUPTED | -2,044 | -2,562 | 25.3 % | 0.50 | 47,703.7 | 8,322.775 | 0.105 | 6,506 | all checks | all checks |
| `extreme_011_seed_1110` | TIME_LIMIT | -518 | -2,774 | 435.5 % | 0.73 | 3,600.1 | 1,518.806 | 0.129 | 11,594 | all checks | all checks |
| `extreme_011_seed_1111` | TIME_LIMIT | -647 | -2,654 | 310.2 % | 0.67 | 3,600.1 | 2,154.512 | 2.015 | 32,058 | all checks | all checks |
| `extreme_011_seed_1112` | TIME_LIMIT | -1,096 | -2,821 | 157.4 % | 0.71 | 3,600.2 | 2,401.778 | 0.143 | 11,936 | all checks | all checks |
| `extreme_011_seed_1113` | TIME_LIMIT | 918 | -2,316 | 352.3 % | 0.72 | 3,600.2 | 580.249 | 1.870 | 15,672 | all checks | all checks |
| `extreme_011_seed_1114` | TIME_LIMIT | 106 | -2,728 | 2,673.6 % | 0.74 | 3,600.3 | 1,897.632 | 0.144 | 13,932 | all checks | all checks |
| `extreme_012_seed_1122` | TIME_LIMIT | -211 | -3,225 | 1,428.4 % | 0.76 | 3,600.2 | 2,448.942 | 0.127 | 11,178 | all checks | all checks |
| `extreme_014_seed_1140` | TIME_LIMIT | 5,509 | -1,305 | 123.7 % | 0.95 | 3,600.1 | 2,189.371 | 0.210 | 20,473 | all checks | all checks |
| `extreme_014_seed_1142` | TIME_LIMIT | 5,909 | -1,447 | 124.5 % | 0.90 | 3,600.4 | 660.292 | 6.513 | 48,003 | all checks | all checks |
| `extreme_014_seed_1143` | TIME_LIMIT | 5,063 | -1,806 | 135.7 % | 0.93 | 3,600.3 | 1,406.704 | 0.172 | 21,333 | all checks | all checks |
