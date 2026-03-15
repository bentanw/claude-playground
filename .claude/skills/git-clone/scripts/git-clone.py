#!/usr/bin/env python3
"""
Clone a GitHub repo, folder, or file into new-git-clone/.
Handles:
  - https://github.com/owner/repo
  - https://github.com/owner/repo/tree/branch/path/to/folder
  - https://github.com/owner/repo/blob/branch/path/to/file
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "git-clone"


def parse_github_url(url: str):
    """
    Returns a dict with keys:
      owner, repo, kind ('repo' | 'tree' | 'blob'), branch, path
    """
    url = url.rstrip("/")
    # Full repo
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)$", url)
    if m:
        return dict(owner=m.group(1), repo=m.group(2), kind="repo", branch=None, path=None)

    # tree (folder) or blob (file)
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/(tree|blob)/([^/]+)/(.*)", url)
    if m:
        return dict(
            owner=m.group(1),
            repo=m.group(2),
            kind=m.group(3),   # 'tree' or 'blob'
            branch=m.group(4),
            path=m.group(5),
        )

    raise ValueError(f"Unrecognised GitHub URL: {url}")


def unique_dest(base: Path) -> Path:
    """Return base if it doesn't exist, otherwise base-2, base-3, …"""
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix  # empty string for directories
    parent = base.parent
    n = 2
    while True:
        candidate = parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def download_file(owner: str, repo: str, branch: str, file_path: str) -> Path:
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
    filename = Path(file_path).name
    dest = unique_dest(OUTPUT_DIR / filename)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {raw_url} → {dest}")
    urllib.request.urlretrieve(raw_url, dest)
    return dest


def clone_folder(owner: str, repo: str, branch: str, folder_path: str) -> Path:
    repo_url = f"https://github.com/{owner}/{repo}.git"
    folder_name = Path(folder_path).name
    dest = unique_dest(OUTPUT_DIR / folder_name)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        print(f"Sparse-cloning {repo_url} (branch={branch}, path={folder_path}) …")
        subprocess.run(
            ["git", "clone", "--no-checkout", "--depth=1", "--filter=blob:none",
             "--branch", branch, repo_url, tmp],
            check=True,
        )
        subprocess.run(
            ["git", "-C", tmp, "sparse-checkout", "set", "--no-cone", folder_path],
            check=True,
        )
        subprocess.run(["git", "-C", tmp, "checkout"], check=True)

        src = Path(tmp) / folder_path
        if not src.exists():
            raise FileNotFoundError(f"Path '{folder_path}' not found in repo after checkout.")
        shutil.copytree(src, dest)

    print(f"Folder cloned → {dest}")
    return dest


def clone_repo(owner: str, repo: str) -> Path:
    repo_url = f"https://github.com/{owner}/{repo}.git"
    dest = unique_dest(OUTPUT_DIR / repo)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Cloning {repo_url} → {dest}")
    subprocess.run(["git", "clone", "--depth=1", repo_url, str(dest)], check=True)
    return dest


def main():
    parser = argparse.ArgumentParser(description="Clone a GitHub repo / folder / file.")
    parser.add_argument("url", help="GitHub URL")
    args = parser.parse_args()

    info = parse_github_url(args.url)
    kind = info["kind"]

    if kind == "blob":
        dest = download_file(info["owner"], info["repo"], info["branch"], info["path"])
    elif kind == "tree":
        dest = clone_folder(info["owner"], info["repo"], info["branch"], info["path"])
    else:  # full repo
        dest = clone_repo(info["owner"], info["repo"])

    print(f"\nDone. Output: {dest}")


if __name__ == "__main__":
    main()
