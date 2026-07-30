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
