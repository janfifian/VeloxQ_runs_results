# How to verify the results

Every command is run from the root of this repository, unless it says otherwise.

## What you need

Three levels; each step says which it needs.

1. **Checksums**: `sha256sum` (Linux, Git Bash on Windows; `shasum -a 256 -c` on macOS).
2. **Stand-alone checks**: Python 3 with numpy, h5py and PyYAML. No other code.
3. **Recomputation**: the authors' code repository, which is not public (the compiler and the
   instance generator are closed), with its Python environment and a Gurobi licence. These
   commands run from the root of that repository, where this repository's folders sit in
   `repository_ready/` and `veloxq/` sits at `repository_ready/veloxq_synthetic`. They are listed
   so that the checks the authors ran, and their expected output, are on record.

What can be checked: the paper's statistics, from the deposited results (all three levels); the
compilation, in part: the QUBO matrices are deposited with their variable maps, and level 2
evaluates every VeloxQ answer's energy on its matrix, but how a matrix was compiled from the
model cannot be checked without the compiler. The experiments cannot be repeated from this
repository: the compiler and the generator are closed, and VeloxQ is a commercial product; the
run records give each run's settings and software versions, and each VeloxQ call's job id.

## 1. Checksums (level 1)

    cd instances && sha256sum -c SHA256SUMS                  # 200 files
    cd milp_synthetic_weighted && sha256sum -c SHA256SUMS    # 406 files
    cd milp_3studies_cold && sha256sum -c SHA256SUMS         # 32 files
    cd veloxq_3studies && sha256sum -c SHA256SUMS            # 131 files
    cd dwave_capacity && sha256sum -c SHA256SUMS             # 44 files
    cd veloxq && sha256sum -c SHA256SUMS                     # 9,942 files

(each from the root). Expected: `OK` for every file. Every run record names its instance by the
sha256 in `instances/registry.csv` (for `3_studies`, the hash of the original instance; the
published copy is `instances/3_studies/3_studies_instance.yaml`, whose hash the registry gives
in `pseudonymised_sha256`).

## 2. VeloxQ on the synthetic suite, stand-alone (level 2, about 20 minutes)

    python veloxq/scripts/verify_veloxq_deposit.py --root veloxq

It checks every file against `SHA256SUMS`; every VeloxQ call's files against its run record (job
id, the hashes of the samples, of the server's file and of the best state) and its energies on its
QUBO file; the analysis tables against the records; every repaired timetable's links (its input,
its instance and its verdict, by sha256); and it recomputes the repair tables from the records.
Expected: `all checks passed`.

## 3. Recomputation (level 3, in the authors' code repository)

Timetables against their instance, with the verifier (the exact room assignment included):

    python scripts/verify_timetables.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml \
        --timetable repository_ready/instances/certificates/easy_000_seed_1000_certificate.yaml
    python scripts/verify_timetables.py --instance repository_ready/instances/synthetic/hard_008_seed_1080.yaml \
        --timetable repository_ready/milp_synthetic_weighted/hard/hard_008_seed_1080_MIP_solution.yaml
    python scripts/verify_timetables.py --instance repository_ready/instances/3_studies/3_studies_instance.yaml \
        --timetable repository_ready/milp_3studies_cold/production/3_studies_instance_MIP_solution.yaml

Expected: `full True`, a room for every in-person lesson (the last: the MILP's best timetable on
the pseudonymised `3_studies`, 130 lessons).

The repaired S3 answers, each checked again and compared with its deposited verdict:

    python scripts/verify_timetables.py --repair-run repository_ready/veloxq_synthetic/repair/S3_room_set_rows
    python scripts/verify_timetables.py --repair-run repository_ready/veloxq_synthetic/repair/S3_room_set_rows_k3_targeted

Expected: `192 of 192 deposited verdicts reproduced; 188 of 192 timetables pass every check`, and
`4 of 4 ...; 1 of 4 ...`.

The four calls the repair leaves invalid:

    python checks/two_move_neighbourhood.py --run repository_ready/veloxq_synthetic/repair/S3_room_set_rows \
        --caches repository_ready/veloxq_synthetic --out two_moves.json

Expected: for each of the four, `valid after a 1-move 0` and `valid after a 2-move 0`, and
`two_moves.json` equal to `veloxq/repair/S3_room_set_rows/two_move_neighbourhood.json`.

The analysis tables recomputed (the first command decodes and checks the 16 lowest-energy samples
of each of the 1,344 calls, which takes hours):

    python scripts/analyze_veloxq_campaign.py --root repository_ready/veloxq_synthetic --out recheck --top-k 16
    python scripts/analyze_veloxq_repair.py --root repository_ready/veloxq_synthetic --out recheck
    python scripts/verify_veloxq_deposit.py --root repository_ready/veloxq_synthetic --compare-analysis recheck

Expected: every table `identical`.

The energy check:

    python scripts/check_energy_separation.py --root repository_ready/veloxq_synthetic \
        --milp repository_ready/milp_synthetic_weighted --out recheck --neighbours easy_003_seed_1030 \
        medium_005_seed_1050 medium_006_seed_1061 hard_008_seed_1084 hard_009_seed_1090

Expected: `recheck/energy_separation.csv` and `recheck/optimum_neighbours.csv` hold the values of
the files of the same name in `veloxq/analysis`.

Tables 4-6 and the in-text numbers of Section 7.1 from these files (seconds):

    python paper/figures/make_figures.py --only veloxq-settings
    git status --short paper/figures

Expected: no output from the second command. Run in full, `make_figures.py` computes every table,
figure and in-text number of the paper from the run records (the authors' copies of the runs
whose files are here), and stops with an error if the data no longer support a statement of the
text. The copies of `make_figures.py` and
`check_energy_separation.py` in `veloxq/scripts/` are the versions the VeloxQ deposit was made
with; `make_figures.py` prints a note when they differ from the files it runs with.

The D-Wave capacity analysis: `python -m pytest tests/unit/test_dwave_capacity.py -q` (the tests
pass); the README of `dwave_capacity/` gives the command behind every result file.
