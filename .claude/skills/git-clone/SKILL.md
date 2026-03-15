---
name: git-clone
description: Clone a GitHub repo, a specific folder, or a specific file into outputs/git-clone/. Use when the user provides a GitHub URL and wants to clone it or a subfolder/file from it.
---

# Git Clone Skill

Clone a full GitHub repo, a specific subfolder, or a single file into the `new-git-clone/` directory.

## Usage

```bash
python3 scripts/clone.py "<github_url>"
```

The URL can be:
- A full repo: `https://github.com/owner/repo`
- A folder inside a repo: `https://github.com/owner/repo/tree/branch/path/to/folder`
- A file inside a repo: `https://github.com/owner/repo/blob/branch/path/to/file.md`

## Behavior

- Output always goes into `outputs/git-clone/`
- If a file or folder with the same name already exists there, a number is appended (e.g. `SKILL-2.md`, `my-folder-2/`)
- For folders: uses git sparse-checkout so only the target path is downloaded
- For files: downloads the raw file directly

## Examples

Clone a single file:
```bash
python3 scripts/clone.py "https://github.com/ComposioHQ/awesome-claude-skills/blob/master/template-skill/SKILL.md"
```

Clone a folder:
```bash
python3 scripts/clone.py "https://github.com/ComposioHQ/awesome-claude-skills/tree/master/template-skill"
```

Clone a full repo:
```bash
python3 scripts/clone.py "https://github.com/owner/repo"
```
