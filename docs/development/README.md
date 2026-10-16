# Development

Install the package and its development tools in a virtual environment:

```bash
python -m pip install -e ../orbit-core -e '.[dev]'
pytest --cov=orbit_cli --cov-report=term-missing
ruff check .
ruff format --check .
mypy
python -m build
```

Supported Python versions are 3.11 through 3.14. Changes to keyboard, mouse, prompts, or plugin
dispatch should include Textual pilot tests. Keep provider-specific behavior in its package and
test this package against the public Core extension contract.
