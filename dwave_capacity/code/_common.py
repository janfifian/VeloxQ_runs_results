"""Shared setup for the real-data checks in this folder (see README.md)."""
from __future__ import annotations

import importlib.util
import io
import contextlib
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[1]

# Last commit before the pre-rerun fixes (07e1b9c); used as "before the fix".
PRE_FIX = "a44b0e0"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "new_experiments" / "scripts"))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from _pipeline_helpers import setup_environment  # noqa: E402

setup_environment(REPO)


def module_at(revision: str, repo_path: str, name: str) -> ModuleType:
    """Import ``repo_path`` as it was at ``revision`` (read with ``git show``)."""
    source = subprocess.run(["git", "-C", str(REPO), "show", f"{revision}:{repo_path}"],
                            capture_output=True, check=True).stdout
    path = Path(tempfile.mkdtemp(prefix="check_")) / f"{name}.py"
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def quietly(fn, *args, **kwargs):
    """Call ``fn`` with its stdout discarded (the compiler prints progress)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def load_instance(rel_path: str):
    from etpmachine.ETPMachine_ProblemInstance import ProblemInstance

    def _load():
        pi = ProblemInstance.from_yaml(str(REPO / rel_path))
        pi.rebuild_derived()
        return pi
    return quietly(_load)


def qubo_candidates(pi):
    """Candidate placements, slots and group map as the QUBO compiler builds them."""
    import yaml
    from etpmachine.ETPMachine_QUBO import precompute_time_alloc_data

    with open(REPO / "cfg" / "qubo_cfg_3_studies.yaml", encoding="utf-8") as fh:
        cfg = dict(yaml.safe_load(fh)["time_allocation"])
    cfg["enable_mixed_modality"] = False   # the pair set itself is what the checks build
    return quietly(precompute_time_alloc_data, pi, cfg), cfg
