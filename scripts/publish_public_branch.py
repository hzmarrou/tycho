#!/usr/bin/env python3
"""Sync the `public` branch to the curated Tycho distribution from main.

The `public` branch is the GitHub-facing version of Tycho: it contains
only the curated subset that ``export_tycho_public.py`` produces.
Visitors who land on https://github.com/<org>/tycho see this branch
(once it's set as the default on GitHub).

Workflow:

    # Daily — edit on main, push, then sync:
    git push origin main
    python scripts/publish_public_branch.py

This script:
  1. Runs ``scripts/export_tycho_public.py`` to refresh ``dist/tycho-public/``.
  2. Creates a temporary worktree on the ``public`` branch (creating
     the branch as an orphan the first time).
  3. Wipes the worktree contents and replaces them with the curated
     subset.
  4. Commits and pushes if anything changed.
  5. Removes the temporary worktree.

Your main worktree is never touched; the sync happens in
``.worktrees/public-sync/`` and is cleaned up afterwards.

First-time setup (one-time):

    python scripts/publish_public_branch.py
    # Then on GitHub: Settings → Branches → Default branch → public

After that, visitors browsing https://github.com/<org>/tycho see the
curated version. The full ``main`` branch is still pushed and
available for collaborators who need it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = REPO_ROOT / "dist" / "tycho-public"
TEMP_WORKTREE = REPO_ROOT / ".worktrees" / "public-sync"
BRANCH = "public"


def _run(cmd: list[str], *, cwd: Path = REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess with stdout/stderr inherited; raise on non-zero
    if ``check=True``."""
    return subprocess.run(cmd, cwd=str(cwd), check=check)


def _run_capture(cmd: list[str], *, cwd: Path = REPO_ROOT) -> str:
    """Run a subprocess and return its trimmed stdout."""
    result = subprocess.run(
        cmd, cwd=str(cwd), check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _refresh_export() -> None:
    """Rebuild ``dist/tycho-public/`` from current main."""
    print("Step 1/5: refreshing the curated export...")
    _run([sys.executable, str(REPO_ROOT / "scripts" / "export_tycho_public.py")])


def _main_sha() -> str:
    """Commit SHA of the current main branch (or current HEAD if main
    isn't checked out)."""
    return _run_capture(["git", "rev-parse", "HEAD"])


def _public_branch_exists() -> tuple[bool, bool]:
    """Return ``(local_exists, remote_exists)`` for the public branch."""
    local = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{BRANCH}"],
        cwd=str(REPO_ROOT), capture_output=True,
    ).returncode == 0
    remote = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{BRANCH}"],
        cwd=str(REPO_ROOT), capture_output=True,
    ).returncode == 0
    return local, remote


def _ensure_public_worktree() -> bool:
    """Create or recreate the temp public-sync worktree.

    Returns True if this was the first-ever public sync (orphan branch
    created), False if the branch already existed somewhere.
    """
    # Clean up any stale worktree from a prior run.
    if TEMP_WORKTREE.exists():
        _run(
            ["git", "worktree", "remove", "--force", str(TEMP_WORKTREE)],
            check=False,
        )

    local, remote = _public_branch_exists()

    if local:
        print(f"Step 2/5: attaching public-sync worktree (existing local {BRANCH} branch)...")
        _run(["git", "worktree", "add", str(TEMP_WORKTREE), BRANCH])
        return False

    if remote:
        print(f"Step 2/5: fetching existing remote {BRANCH} branch and attaching worktree...")
        _run(["git", "fetch", "origin", BRANCH])
        _run(["git", "worktree", "add", str(TEMP_WORKTREE), "-b", BRANCH, f"origin/{BRANCH}"])
        return False

    print(f"Step 2/5: creating {BRANCH} as a fresh orphan branch (first-time setup)...")
    _run(["git", "worktree", "add", "--detach", str(TEMP_WORKTREE)])
    _run(["git", "checkout", "--orphan", BRANCH], cwd=TEMP_WORKTREE)
    # Unstage everything inherited from the detached checkout.
    _run(["git", "rm", "-rf", "--quiet", "."], cwd=TEMP_WORKTREE, check=False)
    return True


def _replace_worktree_contents() -> None:
    """Wipe the temp worktree and copy the curated export into it."""
    print("Step 3/5: replacing worktree contents with the curated export...")
    for item in TEMP_WORKTREE.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    for item in EXPORT_DIR.iterdir():
        dest = TEMP_WORKTREE / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copyfile(item, dest)


def _commit_and_push(main_sha: str, no_push: bool, first_time: bool) -> bool:
    """Stage, commit if anything changed, push if requested.

    Returns True if a commit was created, False if the public branch
    was already up to date.
    """
    print("Step 4/5: staging and committing...")
    _run(["git", "add", "-A"], cwd=TEMP_WORKTREE)
    diff_check = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(TEMP_WORKTREE),
    )
    if diff_check.returncode == 0 and not first_time:
        print("  No changes — public branch already matches the curated subset.")
        return False

    message = (
        f"public: initial curated distribution from main @ {main_sha[:8]}"
        if first_time
        else f"public: sync from main @ {main_sha[:8]}"
    )
    _run(["git", "commit", "-m", message], cwd=TEMP_WORKTREE)

    if no_push:
        print("Step 5/5: --no-push set; skipping push.")
        return True
    print(f"Step 5/5: pushing {BRANCH} to origin...")
    push_cmd = ["git", "push", "origin", BRANCH]
    if first_time:
        push_cmd.insert(2, "-u")
    _run(push_cmd, cwd=TEMP_WORKTREE)
    return True


def _cleanup() -> None:
    """Remove the temp worktree."""
    if TEMP_WORKTREE.exists():
        _run(["git", "worktree", "remove", "--force", str(TEMP_WORKTREE)], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit to the public branch locally but skip the push.",
    )
    args = parser.parse_args()

    try:
        _refresh_export()
        first_time = _ensure_public_worktree()
        _replace_worktree_contents()
        committed = _commit_and_push(_main_sha(), args.no_push, first_time)
    finally:
        _cleanup()

    if first_time:
        print(
            "\nFirst-time setup complete. Next: in GitHub -> Settings -> "
            "Branches, change the default branch to `public` so visitors "
            "see the curated version."
        )
    elif committed:
        print("\nDone. Public branch now reflects the latest main.")
    else:
        print("\nNothing to do — public branch was already in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
