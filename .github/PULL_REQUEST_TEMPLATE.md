<!-- Thanks for contributing! Please keep PRs small and focused. -->

## Summary

<!-- What does this change do, and why? -->

## Related issue

<!-- e.g. "Closes #12". Delete if not applicable. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor / internal
- [ ] Other:

## Checklist

- [ ] `pytest -q` passes locally
- [ ] `ruff check src tests docs` is clean
- [ ] Docs updated if public API changed (`uv run sphinx-build -b html docs docs/_build/html`)
- [ ] Added/updated tests for the change
- [ ] If dependencies changed: re-ran `uv lock` and committed `uv.lock` alongside
      `pyproject.toml`
- [ ] I read [`AGENTS.md`](../AGENTS.md) and this change is consistent with its
      design conventions — in particular, FITS files are opened with
      `fitstoolz.utils.open_fits` and axes are addressed by name
