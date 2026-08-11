# Contributing to NEXUS AI

## Development Setup

1. **Clone the repository**
   ```powershell
   git clone https://github.com/HIMANSHU11827/NEXUS.git
   cd NEXUS
   ```

2. **Create a virtual environment**
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

3. **Install the project in editable mode**
   ```powershell
   pip install -e .
   ```

4. **Install dev dependencies**
   ```powershell
   pip install -e ".[dev]"
   ```

5. **GUI setup** (if working on the frontend)
   ```powershell
   cd gui
   npm install
   ```

## Code Style

- **Python**: Use [ruff](https://docs.astral.sh/ruff) for linting and formatting.
  ```powershell
  ruff check .
  ```
  Configuration is in `pyproject.toml`: select `E`, `F`, `I`; ignore `E501` (line length).

- **Type checking**: Use [pyright](https://github.com/microsoft/pyright) in basic mode.
  ```powershell
  pyright .
  ```

- **Conventions**:
  - Follow existing patterns in the codebase (see `AGENTS.md` for architecture).
  - Use descriptive variable and function names.
  - Avoid adding unnecessary comments unless the logic is non-obvious.

## Testing

- Run the Python test suite:
  ```powershell
  python -m pytest tests/ -v
  ```

- If you change GUI code, verify the build:
  ```powershell
  cd gui && npm run build
  ```

- If you change TUI code, verify the build and tests:
  ```powershell
  cd tui && npm run build && npm test
  ```

- Ensure all existing tests pass before submitting a pull request.

## Pull Request Process

1. Create a feature branch from `main`.
2. Make your changes, following the code style and testing guidelines above.
3. Write or update tests to cover your changes.
4. Run the full test suite and ensure lint passes.
5. Commit your changes using conventional commit messages.
6. Open a pull request against `main`.
7. Ensure the PR description describes the change, type, and testing done (use the PR template).

## Commit Message Style

Use [conventional commits](https://www.conventionalcommits.org/):

```
<type>: <short description>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `style`, `chore`, `perf`.

Examples:
- `feat: add deep research tool with sub-agent spawning`
- `fix: handle missing provider key in gateway startup`
- `docs: update README with new launch modes`
