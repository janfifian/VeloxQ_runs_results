# Instances

The instances of the paper that are certified feasible under the rules of the
current code, ready to use, each with its certificate; only such instances are
here (for LATO and 3_studies see below). Nothing here has to be generated. The
folder is written by `scripts/assemble_repository_instances.py` from the
certificates of `scripts/certify_instance_feasibility.py`.

## What is here

- `synthetic/` -- the 64 synthetic instances: easy 20, medium 15, hard 20,
  extreme 9 (`extreme_011` five seeds, `extreme_012` one, `extreme_014` three).
  They come from the authors' generator, which is not published.
- `3_studies/` -- the production instance `3_studies`, pseudonymised (below).
- `certificates/` -- for every instance (and 3_studies), `<name>_certificate.yaml`, a complete
  timetable with rooms (each lesson a day, a time and a lecturer; each
  in-person lesson a room; remote lessons need no physical room and carry
  none), and `<name>_certificate.json`, the verdicts, the solver status and
  time, the instance sha256 and the code commit.
- `registry.csv`, `registry.json` -- one row per instance: file (or, for
  3_studies, its path in the code repository), sha256, verdicts, certificate
  and its sha256, code commit, and for 3_studies the pseudonymised copy and
  its sha256.
- `room_capacity_check.json` -- the room counting check of every synthetic
  instance, a necessary condition for a timetable with rooms (all 64 pass).
- `SHA256SUMS` -- checksums of every file here (`sha256sum -c SHA256SUMS`).

## How feasibility was certified

For every instance, the time-allocation MILP with the current rules was
solved for feasibility only (constant objective): room rows on every
15-minute cell, a 15-minute break between consecutive lessons of a group or a
lecturer (each lesson widened by 7.5 minutes on both sides), PR5 for every
group and lecturer, and the RU3 room filter (a course may use only rooms with
at least as many seats as it has students). The plan then went through the
verifier: the time core (course hours, the limit on lesson blocks, no
overlapping lessons of a lecturer or a group, lecturer availability, the
lecturer assigned to the course), the room rows, an exact assignment of rooms
to the in-person lessons (each lesson one admissible free room, no two
overlapping lessons in one room; a small MILP), the 15-minute break and PR5. The certificate is that plan with its rooms, checked
once more with the room map: one admissible room per in-person lesson, no room
used by two lessons at once, capacity, availability. Travel time between rooms
(RU1) is a preference of the room stage and is not part of the certificate.

## Hashes

`sha256` in the registry is the plain `sha256sum` of the file in this folder.
The files have LF line ends and `.gitattributes` keeps git from converting
them on Windows. The code hashes instance files the same way on any checkout
(CRLF is turned into LF before hashing, `run_record.content_sha256`), so the
instance hash in a run record can be matched against this registry.

## LATO

Not included yet: it has no feasibility certificate. On 08.10.2026 the
certification MILP under the current rules (131 million rows) ran out of
memory at the root relaxation, so neither a plan nor a proof of infeasibility
exists. 99.8 % of those rows are the pairwise rows of PR5 (the break between
online and in-person lessons), so LATO is run without PR5, as in the paper,
and needs a certificate under a profile without PR5. The instance
(`artifacts/Corrected_lato_3fix.yaml`, the 3-fix version with the two 250-seat
auditoriums, de-identified) is added here once it is certified.

## 3_studies

Certified in the same way. The instance names real people, so it is here
pseudonymised (`3_studies/3_studies_instance.yaml`), and so is its certificate
(`certificates/3_studies_instance_certificate.yaml` and `.json`): lecturers,
courses and their codes, programmes, institutes, faculties other than FTIMS,
buildings and rooms are replaced by tokens (`Lecturer07`, `Course 12`,
`00 00 0031 00`, `PA`, `Instytut_C`, `BA-04`, ...), with one map for the
instance and every file of its runs, and the lecturers' free-text requests and
the rooms' comments are emptied. Numbers, slots, capacities, availabilities,
lesson types and the remote, language-centre and sports-centre markers are
unchanged, so the copy loads like the original and a timetable checks against
it exactly as against the original. The registry
names the original by its path in the code repository
(`artifacts/3studies/3_studies_instance.yaml`, `instance_in_folder` false) and
its sha256, the hash the run records use, and the pseudonymised copy in
`pseudonymised_copy` and `pseudonymised_sha256`.
