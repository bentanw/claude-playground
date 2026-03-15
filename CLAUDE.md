# Claude Playground — Global Rules

## Python Scripts & Dependencies

Whenever a Python script requires `pip install` (or `pip3 install`), **never install packages globally**.
Instead, always:

1. Use the **single shared venv at the project root** (`/Users/bentan/Codebase/claude-playground/venv/`). Create it once if it doesn't exist:
   ```bash
   python3.11 -m venv venv
   ```
2. Install dependencies into it:
   ```bash
   venv/bin/pip3 install <package>
   ```
3. Run scripts with the shared venv's interpreter (always from the project root):
   ```bash
   venv/bin/python3 .claude/skills/<skill>/scripts/my_script.py
   ```

This applies to **all skills and all scripts** in this repo. Never create per-skill venvs.
