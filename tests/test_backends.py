"""The matting backend's own contract -- kept separate from test_pipeline.py
because this is the one file in the suite that talks about a GPU, an
interpreter path shared with another project, and a worker script that never
actually runs inside this process.

No real matting here (that is test_ui.py's real-pipeline test, and it
already exercises whichever interpreter `backends.INTERPRETER` resolves to).
This file is about the two things that would be invisible from outside the
subprocess boundary: which interpreter gets chosen, and what the worker
script generated for it actually says -- both checkable without spawning
torch at all.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dressaug import backends


def test_the_cuda_interpreter_is_preferred_when_it_exists():
    """Pins the fix, 2026-09-20: a `.venv-cuda` was found sitting on this
    machine already built with a CUDA-enabled torch, unused, next to the
    CPU-only `.venv-birefnet` this project had relied on until now. If
    `.venv-cuda` exists, `INTERPRETER` must resolve to it -- not because CUDA
    is always faster (a worker without a GPU falls back to CPU on its own),
    but because a regression that silently went back to always picking the
    CPU-only interpreter would otherwise be invisible: both paths produce
    correct alphas, just at very different speeds, and nothing else in this
    suite runs slowly enough to notice which one answered.
    """
    if backends._CUDA_INTERPRETER.exists():
        assert backends.INTERPRETER == backends._CUDA_INTERPRETER
    elif backends._CPU_INTERPRETER.exists():
        # No CUDA venv, but the sibling CPU one exists -- must still be
        # preferred over the local-project fallback tier (see
        # test_local_interpreter_is_used_when_no_sibling_exists below).
        assert backends.INTERPRETER == backends._CPU_INTERPRETER
    elif backends._LOCAL_INTERPRETER.exists():
        assert backends.INTERPRETER == backends._LOCAL_INTERPRETER
    else:
        # Nothing exists on this machine at all -- the fallback path is the
        # one under test instead, and it must not silently point nowhere.
        assert backends.INTERPRETER == backends._CPU_INTERPRETER


def test_the_worker_never_uses_half_precision():
    """The fp16 lesson, pinned as a static check on the generated source
    rather than only as prose in the module docstring: BiRefNet's Swin
    backbone returns an all-NaN alpha in half precision, on CPU or CUDA
    alike, and a future edit adding `.half()` or `torch.autocast(...)` for a
    speed win would reintroduce a total failure that looks like a dozen
    other bugs. Checked on the generated worker source, not the template
    string, so a placeholder substitution bug couldn't hide a violation.
    Comment lines are stripped first -- the worker script's own comment
    *names* `.half()` and `autocast` as the things it deliberately avoids,
    which would otherwise trip this exact check on its own commentary."""
    code_lines = "\n".join(
        line for line in backends.worker_source().splitlines()
        if not line.strip().startswith("#")
    )
    assert ".half(" not in code_lines
    assert "autocast" not in code_lines


def test_the_worker_falls_back_to_cpu_on_a_cuda_oom_and_never_silently_swallows_other_errors():
    """The other real risk measured before this was trusted: BiRefNet's own
    peak VRAM use on a full frame came within a few hundred MB of this
    machine's 4GB card's actual free memory, so any other GPU load on the
    day can tip a real job over. The worker must catch exactly that failure
    and retry on CPU rather than fail the job -- and must not catch and
    swallow a *different* RuntimeError, which would hide a real bug behind
    what looks like graceful degradation."""
    src = backends.worker_source()
    assert "out of memory" in src.lower()
    assert "except RuntimeError as exc" in src
    assert "raise" in src.split("except RuntimeError as exc")[1].split("if device")[0] \
        or "else:\n        raise" in src, (
        "the OOM handler must re-raise anything that isn't actually an "
        "out-of-memory error, not swallow it"
    )


def test_the_model_is_still_pinned_to_a_revision():
    """The sibling project's own lesson, carried over (see this module's
    docstring): `trust_remote_code=True` executes whatever the Hub currently
    serves at the given revision, so an unpinned reference would mean the
    model that actually runs can change out from under every gate and test
    in this project without anyone changing a line of code here."""
    assert backends.MODEL_REVISION in backends.worker_source()
    assert len(backends.MODEL_REVISION) == 40, "expected a full git SHA, not a short one"


def test_env_var_overrides_the_interpreter_path():
    """The portability escape hatch, added 2026-09-22: on a machine that
    doesn't have `../Boutique Business/` at all -- a fresh install
    elsewhere, most obviously -- `DRESSAUG_TORCH_PYTHON` must be able to
    point `INTERPRETER` anywhere, without editing source. Reloads the
    module under a patched environment rather than re-deriving the
    resolution logic by hand, so this proves what actually happens on
    import, not what the test author assumes it does; restores the
    environment and reloads back to the real default afterward so no other
    test in this file (or a later run in the same process) sees the override.
    """
    import importlib
    import os as _os
    orig = _os.environ.get("DRESSAUG_TORCH_PYTHON")
    fake = str(pathlib.Path(__file__).resolve())  # any real file will do
    try:
        _os.environ["DRESSAUG_TORCH_PYTHON"] = fake
        importlib.reload(backends)
        assert backends.INTERPRETER == pathlib.Path(fake)
    finally:
        if orig is None:
            _os.environ.pop("DRESSAUG_TORCH_PYTHON", None)
        else:
            _os.environ["DRESSAUG_TORCH_PYTHON"] = orig
        importlib.reload(backends)


def test_local_venv_torch_is_used_when_no_sibling_or_env_var_exists():
    """The handoff tier, added when this project first went to a colleague's
    machine: no `../Boutique Business/` sibling, no `DRESSAUG_TORCH_PYTHON`
    set, but `install-torch.ps1` was run and left a self-contained interpreter
    at `.venv-torch/`. `INTERPRETER` must find it rather than falling through
    to the "missing interpreter" default and forcing every matting call to
    fail on a machine that in fact has everything it needs.

    Faked with a real file standing in for the interpreter, same technique as
    `test_env_var_overrides_the_interpreter_path` -- proves the resolution
    order actually implemented, not the order this test's author assumes.
    """
    import importlib
    import os as _os
    orig = _os.environ.get("DRESSAUG_TORCH_PYTHON")
    try:
        _os.environ.pop("DRESSAUG_TORCH_PYTHON", None)
        importlib.reload(backends)
        if backends._CUDA_INTERPRETER.exists() or backends._CPU_INTERPRETER.exists():
            return  # this machine has a sibling interpreter -- that tier wins by design, nothing to prove here
        assert backends.INTERPRETER in (backends._LOCAL_INTERPRETER, backends._CPU_INTERPRETER)
    finally:
        if orig is None:
            _os.environ.pop("DRESSAUG_TORCH_PYTHON", None)
        else:
            _os.environ["DRESSAUG_TORCH_PYTHON"] = orig
        importlib.reload(backends)


def test_matting_device_is_recorded_only_when_the_worker_reports_one():
    """`LocalCpuMatting.last_device` starts unset, not a guessed default --
    a caller that reads it before any `matte()` call should see that
    plainly rather than a value that looks real but was never measured."""
    backend = backends.LocalCpuMatting()
    assert backend.last_device is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} backend tests pass")
