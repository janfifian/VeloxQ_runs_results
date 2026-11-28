# Would bigger quantum annealers help? Data and results

The data and results of the paper *Would bigger quantum annealers help? An emulator-based test
of QUBO against MILP on university timetabling*: the instances, and every solver answer,
timetable, verdict and run record of the runs the paper reports, with the scripts that compute
its tables and figures from them. Archived on Zenodo: https://doi.org/10.5281/zenodo.23692152.

## Contents

| folder | what it holds | in the paper |
|---|---|---|
| `instances/` | the 64 certified synthetic instances and the production instance `3_studies` (pseudonymised), each with a feasibility certificate (a complete timetable with rooms), and a registry of their checksums | Sections 6 and 7 |
| `veloxq/` | VeloxQ on the synthetic suite under the seven penalty settings S0-S6 (1,344 calls): every sample, the matrices as submitted, the job ids and run records; the repair of the S3 answers and the repair from an empty timetable; the analysis tables | Section 7.1, Tables 4-6 |
| `milp_synthetic_weighted/` | the time-allocation MILP on the 64 synthetic instances (Gurobi 12.0.3): timetables, run records, Gurobi's solutions and logs | Sections 7.1 and 7.2, Appendix E |
| `veloxq_3studies/` | VeloxQ on `3_studies` under S3 and S0, and the repair of every answer | Section 7.3 |
| `milp_3studies_cold/` | the cold-start MILP on `3_studies`, 12 h of search | Section 7.3, Fig. 3 |
| `dwave_capacity/` | which instances could run directly on a current D-Wave QPU | Appendix D.4 |

Each folder has a README, which says what every file is and how it was made, and a
`SHA256SUMS`. `HOW_TO_VERIFY.md` gives the checks and their expected output.

## The production instance is pseudonymised

`3_studies` is the timetabling instance of a summer semester of one institute, and it names real
lecturers. The instance and every file of its runs are therefore published pseudonymised, with
one map: lecturers, courses and their codes, programmes, institutes, faculties other than FTIMS,
buildings and rooms are replaced by tokens (`Lecturer07`, `Course 12`, `00 00 0031 00`, `PA`,
`Instytut_C`, `BA-04`, ...), the lecturers' free-text requests and the rooms' comments are
emptied, and Gurobi's licence number is removed from the logs. Every number, time slot,
capacity, availability and lesson type is unchanged, and the samples, Gurobi's solutions and the
timetables decode and check against the published instance exactly as against the original. The run records keep the hashes of the original files, which
the published copies do not match; each folder's `SHA256SUMS` lists the published files by their
bytes. The map is not published.

## What is not here

The MILP-to-QUBO compiler and the instance generator are closed, and VeloxQ is a commercial
product, so the runs cannot be repeated from this repository; the run records give every run's
settings and software versions, and every VeloxQ call's job id. LATO, the second real instance,
enters only an appendix of the paper and has no feasibility certificate; it is not here.

## Files

Every text file has Unix line ends, and `.gitattributes` keeps git from converting them; every
`SHA256SUMS` gives the sha256 of each file's bytes (`sha256sum -c SHA256SUMS`).
