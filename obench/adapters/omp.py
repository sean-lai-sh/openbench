"""Oh My Pi (`omp`) uses the Pi adapter's headless runner.

The A/B runner sets ``OBENCH_PI_VERTEX`` with Oh My Pi's config directory
(``OMP_CODING_AGENT_DIR``, ``models.yml``) and the built ``omp`` binary.
"""

import importlib.util
from pathlib import Path

NAME = "omp"
_PI = None


def _pi():
    global _PI
    if _PI is None:
        path = Path(__file__).with_name("pi.py")
        spec = importlib.util.spec_from_file_location("obench_pi_for_omp", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PI = module
    return _PI


def run(instruction, workdir, model, timeout_s):
    return _pi().run(instruction, workdir, model, timeout_s)


def version():
    return _pi().version()
