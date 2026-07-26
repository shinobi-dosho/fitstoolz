# Contributing to fitstoolz

Thanks for your interest in contributing! **fitstoolz** is a small library and
command-line toolkit for working with FITS images in an intuitive way — labelled
axes, consistent indexing between image and coordinate data, and dask/xarray
under the hood. It's early-beta software, so the most valuable contributions
right now are bug reports, focused fixes, tests, documentation, and FITS files
that break it.

By participating you agree to abide by our
[Code of Conduct](https://github.com/shinobi-dosho/fitstoolz/blob/main/CODE_OF_CONDUCT.md).

## Scope and philosophy

fitstoolz aims to make the *obvious* thing work: axes have names, the names mean
the same thing on the data and on the coordinates, and you shouldn't have to
remember whether FITS or numpy ordering applies at a given moment. We favour
small, focused changes, and prefer solving a problem in plain Python over adding
a layer of machinery.

For background on how the project is put together — the reader/apps split, why
each app is a `@shinobi.pystep`, and the conventions a new app should follow —
see **[`AGENTS.md`](https://github.com/shinobi-dosho/fitstoolz/blob/main/AGENTS.md)**.
If you're considering a larger change, opening an issue to discuss it first is a
great way to align before writing code.

## Ways to contribute

- **Report bugs** and request features via [issues](https://github.com/shinobi-dosho/fitstoolz/issues).
  A FITS file (or a snippet that generates one) that reproduces the problem is
  the single most useful thing you can attach.
- **Improve documentation** under `docs/`, or the docstrings that feed the API
  reference.
- **Submit code** — bug fixes, new apps, tests.

## Development setup

The project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --group dev
.venv/bin/pytest
.venv/bin/ruff check src tests docs

# enable the repo's pre-commit hook (once per clone)
git config core.hooksPath .githooks
```

(You can equivalently use `uv run pytest` / `uv run ruff check src tests docs`.)

### The lockfile

`uv.lock` **is** committed, and `uv sync` installs exactly what it pins. CI runs
every job with `--locked`, so the versions the matrix tests are the versions you
ran locally — not whatever PyPI published that morning. When a build goes red,
that keeps "this branch broke it" and "a dependency broke it" as separate,
answerable questions.

That matters more here than in most libraries: as `SECURITY.md` explains, the
FITS and WCS parsing fitstoolz depends on is astropy's (and, underneath
`astropy.wcs`, wcslib's C code). Pinning what we actually test is how a parser
regression gets attributed to a version rather than to a bad afternoon.

The floors in `pyproject.toml` still define what a downstream `pip install`
resolves. The lock binds only this repo's checkouts and CI.

Two consequences worth knowing:

- **Change `pyproject.toml`, re-run `uv lock`, commit both.** CI's `--locked`
  rejects the mismatch, and so does the pre-commit hook.
- **Dependency upgrades are a deliberate commit**, not a side effect of the
  clock: `uv lock --upgrade` (or `--upgrade-package <name>`) produces a
  reviewable diff.

Dependabot (`.github/dependabot.yaml`) opens those upgrade PRs weekly, updating
`pyproject.toml` and `uv.lock` together so they pass the `--locked` jobs.
Dev-tooling and runtime minor/patch bumps arrive batched; a runtime major —
astropy, numpy, pydantic, dask — gets its own PR on purpose. Security updates
are enabled repo-side and are not batched or scheduled: those PRs arrive when an
advisory does.

### The pre-commit hook

Enabling it is the only setup step that is not `uv`'s job — git will not let a
repository turn on an executable hook by itself, which is why the `git config`
above is manual; skip it and you simply get no hook.

`.githooks/pre-commit` is tracked in the repo, and does two things:

1. **On every commit**, runs `ruff check` and `ruff format --check` over the
   staged Python files. This is fast and catches the lint failures that would
   otherwise turn CI red on a one-line change.
2. **Only when the commit touches `pyproject.toml` or `uv.lock`**, checks the
   lock is in sync with `pyproject.toml`, then runs `pip-audit` over the locked
   runtime dependencies.

The dependency half is gated because pip-audit is a network round trip per
package — tens of seconds. Charging that to a docstring fix teaches people to
reach for `--no-verify`, and it cannot tell them anything new about a dependency
set they have not touched. It installs nothing and pins nothing: pip-audit comes
from the `audit` dependency group via `uv run`, so it and CI's `audit` job check
the same versions with the same commands.

> **Note:** this repo used to use the [pre-commit](https://pre-commit.com)
> framework (`.pre-commit-config.yaml`) for its ruff hooks. It doesn't any more.
> The two mechanisms are mutually exclusive — `core.hooksPath` makes git ignore
> `.git/hooks/`, where `pre-commit install` puts its shim — so everything now
> lives in the tracked `.githooks/pre-commit`. If you have an old clone, run the
> `git config` above; `pre-commit uninstall` is optional but tidy.

Run the audit by hand any time:

```bash
uv export --frozen --no-emit-project --no-default-groups --no-hashes --format requirements-txt |
    uv run --group audit pip-audit --no-deps -r /dev/stdin
```

A finding is usually fixed by `uv lock --upgrade-package <name>`, raising the
floor in `pyproject.toml` too if the vulnerable range is one a downstream install
could still land on. If there is no fixed release and the advisory does not apply
here, pass `--ignore-vuln <ID>` and record why in `pyproject.toml` alongside the
group. `git commit --no-verify` bypasses the hook when you genuinely need to.

## Testing

Run the suite with:

```bash
pytest -q
```

Tests build small synthetic FITS files via the helpers in `tests/__init__.py`;
prefer that over adding binary fixtures to the repo. A few tests pull a sample
image from `data.astropy.org` and will fail without network — that's the
existing arrangement, not a rule to extend. **New tests should be offline.**

**New features and bug fixes should come with tests.** When you fix a
FITS-handling bug, the regression test should construct the header that
triggered it — that header *is* the bug report.

## Code style

- **Lint must be clean**: `ruff check src tests docs` should report no errors.
- `ruff format` is available and uses the same line width.
- The ruff rule set is **pinned explicitly** in `pyproject.toml` under
  `[tool.ruff.lint] select`, rather than inherited from whatever ruff a given
  machine has installed. This is deliberate and has bitten this repo before:
  ruff 0.16.0 widened its default set and turned an untouched `main` red.
  Adopting more rules is a fine thing to decide — but it should be decided, in a
  commit, not arrive with a dependency bump.
- Use **type hints** and write **docstrings** on public API — they render into
  the Sphinx API reference via autodoc. Google-style sections, as the existing
  code uses.
- Match the surrounding code's naming, comment density, and idiom.

### Reading FITS files

Open FITS files with `fitstoolz.utils.open_fits`, never `astropy.io.fits.open`
directly. It enforces the "filenames are paths, never URLs" boundary described
in `SECURITY.md`, and it only works as a boundary because it is the single door.

## Documentation

Docs are built with Sphinx (Furo theme) and hosted on Read the Docs. Build them
locally with:

```bash
uv sync --group docs
uv run sphinx-build -b html docs docs/_build/html
```

Please update the docs when you change public API. If you add a documentation
dependency, keep `docs/requirements.txt` in sync with the `docs` dependency group
in `pyproject.toml` (Read the Docs installs from the former).

## Pull requests

1. Branch off `main` and keep PRs **small and focused** — one logical change per
   PR is much easier to review.
2. Make sure `pytest -q` and `ruff check src tests docs` pass locally, and that docs
   build if you touched public API.
3. Push and open a PR against `main`. Reference any related issue
   (e.g. "Closes #12").
4. **CI must be green.** The `test` job runs the suite and lint across Python
   3.11, 3.12 and 3.13, and the `audit` job runs pip-audit over the locked
   runtime dependencies. That's the merge gate.

### Commit messages

Write clear, descriptive commit messages explaining *why* a change is made. No
formal convention (Conventional Commits, sign-off/DCO, or CLA) is required.

## Versioning and releases

The project follows [Semantic Versioning](https://semver.org/). **Contributors
don't cut releases** — that's a maintainer task. Releases are tag-driven: the
maintainer bumps `version` in `pyproject.toml`, updates `CHANGELOG.md`, and
pushes a `vX.Y.Z` tag; the `release.yml` workflow verifies the tag matches the
package version, builds, tests, and publishes to PyPI. PyPI does not allow a
version to be re-uploaded, even after deletion, so the tag check is a real gate.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](https://github.com/shinobi-dosho/fitstoolz/blob/main/LICENSE).
