# Changelog

All notable changes to fitstoolz are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the
major version is zero, a minor bump may carry breaking changes.

## [Unreleased]

The CLI is now built on shinobi (stimela-ninja, Stimela 3.0) instead of scabha. Each app
is a `@shinobi.pystep` whose typed signature is the single schema authority, so the same
function backs both the `fitstoolz` command line and a shinobi `Recipe` step (or a dosho
tool) — the pattern simms 3.0 already uses.

### Breaking

- **`scabha` is no longer a dependency**; `stimela-ninja>=0.1.0b3`, `pydantic>=2.6` and
  `click>=8.1` are. `omegaconf` is gone with it.
- **The YAML parameter schemas are gone.** `src/fitstoolz/apps/parser_configs/` and
  `fitstoolz.apps.get_app_config` have been removed. Parameters are declared as pydantic
  `Field`s on each app's pystep, and the click options are generated from that model by
  `shinobi.clickutil.build_options`.
- **`fitstoolz.apps.<app>.runit` is a plain function taking an options namespace**, not a
  `click.Command`. Each app module now exposes `step` (the `StepRef`) and `command` (the
  `click.Command`); `fitstoolz.apps.main.app_dict` points at the latter.
- **Boolean options gained a `--no-` form** (`--replace/--no-replace`,
  `--memmap/--no-memmap`, `--show/--no-show`), so a flag defaulting to true can now be
  turned off — `slice --no-memmap` was previously unreachable.
- **`stack --stacked-fits` is now required** and `stack` no longer accepts `--outfile`
  or `--replace`; it writes to `--stacked-fits` and never honoured the other two.
- **`stats` no longer accepts `--outfile` or `--replace`**, which it ignored; it writes
  no files. It now returns `min`/`max`/`mean`/`std` as typed step outputs, computed in
  one pass over the data whether or not `--show` is given.
- **`--temporal-chunks` has been removed** from `slice`, `stack`, `unstack`, `add-axis`
  and `remove-axis`. `FitsData.build_chunks` only ever accepted RA, Dec and spectral
  chunking, so the option did nothing.
- **`add-axis --ctype` and `--index` are now required**, and `--crpix`, `--crval`,
  `--cdelt` and `--cunit` default to `0`, `0.0`, `1.0` and `""`. Omitting any of them
  previously crashed inside `FitsData.add_axis`.
- **`FitsData.fname` is a `pathlib.Path`**, not a `scabha.basetypes.File`. `File`'s
  `.EXISTS` attribute is not available on it; use `.exists()`.

### Added

- Each app returns typed outputs (`FitsOutputs`, `StackOutputs`, `StatsOutputs`), so
  apps can be chained in a shinobi `Recipe` — the output path of one step wires into the
  next.
- `fitstoolz.apps.<app>.step` is a uniform handle on each app's `StepRef`, for callers
  that resolve an app by name rather than by import.

### Security

- **`fitstoolz.utils.open_fits` is now the single door for reading FITS files**, and
  `FitsData`, `get_beam_table`, `expand_along_axis_from_files` and the `header` app all
  go through it. `astropy.io.fits.open` *fetches* a string that looks like a URL (via
  `astropy.utils.data.download_file`), so an unchecked filename argument was an outbound
  network request waiting to happen. The existence check that prevents this previously
  existed at some call sites and not others — `header` and the `--extra-files` path of
  `stack` would have fetched a URL — so which entry point you came through decided
  whether the boundary held. `open_fits` resolves the name to a `Path`, requires it to
  exist locally, and hands astropy the `Path` rather than the original string.
- **Added `SECURITY.md`**, describing the actual surface: FITS files are untrusted input,
  the parsers are astropy's and wcslib's (so dependency freshness *is* the control),
  there is no code-execution path in fitstoolz, filenames are paths and never URLs, and
  every write clobbers its destination while no write ever invents one.
- **A dependency audit now gates commits and CI.** `pip-audit` runs over the locked
  runtime dependencies in the new `audit` CI job, in `release.yml` before publishing, and
  in `.githooks/pre-commit` on any commit touching `pyproject.toml` or `uv.lock` — the
  same two commands in all three places.
- **CI installs from `uv.lock` with `--locked`** instead of resolving fresh from PyPI, so
  the astropy under test is a known version rather than whatever shipped that morning.
  Dependabot (`.github/dependabot.yaml`) opens the upgrade PRs; a runtime *major* —
  astropy, numpy, pydantic, dask — is deliberately never batched.

### Project

- Added `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `AGENTS.md`
  (design conventions — axis ordering, the app module shape, what not to add) and
  `CITATION.cff`, plus GitHub issue/PR templates.
- **Docs restructured**: `docs/source/` flattened to `docs/`, Furo theme, and new
  quickstart, generated CLI reference (`sphinx-click`), API, security and contributing
  pages. `docs/requirements.txt` is what Read the Docs installs.
- **The ruff rule set is pinned explicitly in `pyproject.toml`** and widened to match
  stimela-ninja's (adding `C4`, `DTZ`, `ERA`, `FURB`, `G`, `ISC`, `LOG`, `PGH`, `Q`,
  `T20`, `TID` and others to the existing `E`/`F`/`I`/`E501`). `ruff.toml` is gone.
  Logging calls now use lazy `%` arguments rather than f-strings.
- **The pre-commit *framework* has been replaced by a tracked `.githooks/pre-commit`.**
  The two cannot coexist — `core.hooksPath` makes git ignore `.git/hooks/` — so existing
  clones need `git config core.hooksPath .githooks` once. The hook runs ruff on every
  commit and the dependency audit only on dependency commits.
- `uv sync --group dev` now includes the test toolchain, and the `Repository` and
  `Issue Tracker` URLs point at `shinobi-dosho/fitstoolz` rather than the old
  `SpheMakh/fitstoolz`.

## [0.1.0b3] — 2026-07-10

First release since the package was restructured around `FitsData`. It corrects the
celestial coordinate grids, which were wrong in three compounding ways, and takes test
coverage from 84% to 99%.

### Breaking

- **`FitsData.add_axis` takes different arguments.** It changed from
  `add_axis(name, idx, coord_type, axis_grid, attrs)` to
  `add_axis(name, idx, crval, cdelt, crpix, cunit)`, where `idx` is a 1-based FITS axis
  number. The old signature was never released; this note is for anyone pinned to a
  commit rather than a version.
- **`coords["RA"]` and `coords["DEC"]` return different values.** They are now correct.
  Anything calibrated against the old grids will shift — see *Fixed* below for the size
  of the error.
- **`get_beam_table` returns `False` instead of raising** when a FITS image carries no
  beam and its first axis is not angular. It previously died with
  `AttributeError: module 'astropy.units' has no attribute 'hz'`.
- **`fitstoolz stats --slice` is now a repeatable `CTYPE,START,END` option**, and
  `--clip-below`, `--clip-above` and `--blank-value` are floats. Neither worked before.
- The unused `zarr` optional extra has been removed; `zarr` was never imported.

### Fixed

- **Celestial coordinate grids are built from the WCS.** `set_celestial_dimensions`
  stepped each sky axis by `CDELT` from the world coordinate at the image corner. Three
  things were wrong: `CDELT1` on a `RA---SIN` axis is an angle on the sky, not a
  coordinate increment, so the longitude step is `CDELT1/cos(dec)` — a 1.167× error at
  dec = −31°; `np.linspace(a, a + scale*n, n)` has step `scale*n/(n-1)`, stretching the
  grid by 1.6% at n = 64; and the origin was taken at pixel (0, 0) rather than on the
  reference row.

  The sky grid is not separable under a projection, so a 1-D coordinate array is only
  meaningful along a principal axis. Each axis is now sampled through the reference pixel
  of the other by evaluating the WCS, reproducing `wcs_pix2world` exactly there.
  Longitude is unwrapped so a field straddling RA = 0 stays monotonic. `pixel_size` still
  reports `CDELT`, which is the angular cell and not the coordinate step.

  Downstream, simms was placing FITS sources 78.6 pixels from where the WCS puts them; it
  now agrees to 0.004 pixels.

- **An unclassifiable axis no longer raises.** An axis astropy cannot type (`LINEAR`, or
  a blank `CTYPE`) has a `coordinate_type` of `None`, which produced
  `TypeError: attribute name must be string, not NoneType`. The `except AttributeError`
  could not catch it, and the `da.empty(dimsize, dtype=group)` fallback would have failed
  too, since `group` is an integer rather than a dtype. Such axes now fall back to pixel
  indices, with the dimension named after the `CTYPE`.

- **An over-declared `WCSAXES` is rejected on construction.** astropy drops trailing axes
  with no `NAXISn` from `array_shape`, so the shape guard passed and the mismatch
  resurfaced later as an `IndexError` against `coord_names`. The guard now compares
  `naxis` too, and the error names both shapes.

- **`get_xds` slices the coordinates along with the data.** `fitstoolz slice --axis`
  failed with a `CoordinateValidationError` on mismatched dimension lengths.

- **Beam keywords are read as angles.** `get_beam_table` evaluated
  `getattr(units, header["CUNIT1"].lower())` before checking whether a beam exists. Beam
  axes now default to degrees and honour `CUNIT1` only when it is itself an angle.

- **The `stats` app accepts the options it advertises.** `--slice` lacked the `repeat`
  policy, so scabha split it on commas and the `CTYPE,START,END` parse raised
  `not enough values to unpack`; the clip options declared `int|float`, which scabha does
  not resolve, so they arrived as strings and were compared against a dask array.

- The documentation build declared `project = "simms"`.

### Added

- `fitstoolz.utils.beam_unit(header)`, returning the unit of the `BMAJ`/`BMIN`/`BPA`
  keywords.

### Changed

- `scabha` is now required from PyPI (`scabha>=2.2.0rc2`) rather than as a direct git
  reference, which PyPI rejects for published distributions.
- The `pytest` upper bound was dropped; `pytest-cov` was added to the `tests` group.
- CI now runs `ruff check` in addition to `ruff format --check`, and reports coverage.
- Read the Docs installs with pip and PEP 735 dependency groups. It previously invoked
  `poetry install`, which cannot work against this hatchling project.

### Testing

Coverage rose from 84% to 99% (`reader.py` 79% → 99%, `utils.py` 88% → 98%,
`apps/slice.py` 68% → 100%, `apps/stats.py` 65% → 100%), and the suite grew from 19 to
77 tests. astropy's WCS is the reference throughout: the coordinate grids are asserted
against `wcs_pix2world` rather than against themselves.

[0.1.0b3]: https://github.com/SpheMakh/fitstoolz/releases/tag/v0.1.0b3
