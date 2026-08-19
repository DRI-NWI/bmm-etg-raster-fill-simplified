"""Guard the small files that must ship with the repository.

The workflow once shipped without ``basins/_template/config.toml`` because
``.gitignore`` excluded all of ``basins/``.  A fresh clone then failed on the
first prep command, and most of the test suite errored out.  These checks make
that failure mode loud instead of silent.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Files that live inside an otherwise-ignored data folder but must be tracked.
REQUIRED_FILES = [
    "basins/_template/config.toml",
    "statewide/bps_lookup.json",
]


@pytest.mark.parametrize("rel_path", REQUIRED_FILES)
def test_required_file_exists(rel_path):
    assert (PROJECT_ROOT / rel_path).is_file(), (
        f"{rel_path} is missing.  The prep scripts and the BpS class names "
        f"depend on it; restore it before running the workflow."
    )


@pytest.mark.parametrize("rel_path", REQUIRED_FILES)
def test_required_file_is_not_gitignored(rel_path):
    """A required file that git ignores will not survive a clone."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    if not (PROJECT_ROOT / ".git").exists():
        pytest.skip("not a git working tree")

    # `git check-ignore` exits 0 when the path IS ignored.
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel_path],
        cwd=PROJECT_ROOT, capture_output=True,
    )
    assert result.returncode != 0, (
        f"{rel_path} is excluded by .gitignore, so it will be absent from a "
        f"fresh clone.  Add a negation rule for it."
    )


# ---------------------------------------------------------------------------
# Console encoding
# ---------------------------------------------------------------------------
# On Windows, redirected or captured stdout defaults to the locale code page
# (cp1252 on a US install), not UTF-8.  A single non-ASCII character in a
# printed string raises UnicodeEncodeError there and kills the run, even
# though it works fine on Linux and in an interactive Windows console.
# Keeping the source pure ASCII removes the whole class of failure.

def _py_sources():
    return sorted(PROJECT_ROOT.glob("*.py")) + sorted((PROJECT_ROOT / "tests").glob("*.py"))


@pytest.mark.parametrize(
    "py_file", _py_sources(), ids=lambda p: p.name
)
def test_source_is_ascii(py_file):
    text = py_file.read_text(encoding="utf-8")
    offenders = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for col, ch in enumerate(line, 1):
            if ord(ch) > 127:
                offenders.append(f"{py_file.name}:{lineno}:{col} {ch!r} (U+{ord(ch):04X})")
    assert not offenders, (
        "Non-ASCII characters in source. Windows cannot print these when "
        "output is redirected (cp1252). Use an ASCII equivalent:\n  "
        + "\n  ".join(offenders[:20])
    )
