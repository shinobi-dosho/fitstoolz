# Security Policy

## Supported versions

fitstoolz is early-beta software. Security fixes are applied to the latest
`0.x` release only; there are no long-term-support branches yet.

| Version | Supported |
| ------- | --------- |
| latest `0.x` | ✅ |
| older       | ❌ |

## Reporting a vulnerability

**Please do not report security issues in public GitHub issues.**

Report vulnerabilities privately by email to **sphemakh@gmail.com** (or via
GitHub's [private vulnerability reporting][ghsa] on this repository, if
enabled). Include enough detail to reproduce — affected version, the command or
API call, and a FITS file (or a description of one) that triggers it.

We aim to acknowledge reports within a reasonable time, work with you on a fix,
and credit you in the release notes if you'd like.

[ghsa]: https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability

## Security posture

fitstoolz reads FITS files and writes FITS files. **A FITS file is untrusted
input** — it arrives from a telescope archive, a collaborator, a pipeline stage
someone else ran — and every guarantee below is about what a hostile or simply
malformed one can make fitstoolz do.

### The parsers are astropy's, and that is the point

fitstoolz does not implement a FITS parser, a WCS solver, or a table reader. It
calls `astropy.io.fits.open`, `astropy.wcs.WCS`, and `astropy.table.Table.read`,
and works on what they return. `astropy.wcs` in particular is a wrapper around
**wcslib, a C library**, parsing header strings that came out of the file.

That is a deliberate division of labour, not an omission: a memory-safety bug in
FITS or WCS parsing is astropy's or wcslib's to fix, and re-implementing either
here would mean owning that class of bug with far fewer eyes on it. The
consequence is that **fitstoolz's parser security is a dependency-freshness
problem**, which is why the dependency discipline below is part of this document
rather than a footnote in `CONTRIBUTING.md`.

`requires-python` and the astropy floor (`astropy>=7.0,<8.0`) are what a
downstream `pip install` resolves against; `uv.lock` is what this repo's CI and
contributors actually run.

### There is no code-execution path

fitstoolz never runs a subprocess, never opens a shell, and never evaluates a
string as code. There is no `subprocess`, no `os.system`, no `eval()`/`exec()`,
no `shell=True`, no `pickle`, and no YAML loading anywhere in `src/fitstoolz`.

The single dynamic import — `fitstoolz.apps.lazy_group.LazyClickGroup` calling
`importlib.import_module` — resolves against the **hardcoded** `app_dict` table
built in `fitstoolz.apps.main` from a literal list of app names. A subcommand
name that is not in that table is a click error, not an import; user input never
reaches `import_module`. The indirection exists so `fitstoolz --help` does not
have to import dask, xarray and astropy for every app, and for no other reason.

This is a much smaller surface than the framework fitstoolz's CLI is built on,
and the distinction is worth stating plainly, because the two are easy to
conflate:

**fitstoolz's apps are `@shinobi.pystep`s — ordinary typed Python functions.**
They carry no `command:` string, no `flavour:`, and no cab YAML, so
[stimela-ninja's cab-definition concerns][ninja-sec] (never `eval()` a cab's
`command`, never resolve `dynamic_schema`, never import a cab package) have no
counterpart here. What fitstoolz does inherit from shinobi is the rule about
recipes: **a shinobi recipe is a Python file, and running it executes it.** If
you invoke a fitstoolz step from a recipe, read the recipe first — that is code
by design, and nothing in this document constrains it.

[ninja-sec]: https://github.com/shinobi-dosho/stimela-ninja/blob/main/SECURITY.md

### Filenames are paths, never URLs

`astropy.io.fits.open` accepts a string that looks like a URL and **fetches it**
(`astropy.utils.data.download_file`). Left unchecked, that quietly turns every
`fname` argument — a CLI positional, a `--extra-files` entry, a step input wired
from another pipeline stage — into an outbound network request, with the cache
write and the SSRF reach that implies.

Every FITS read in fitstoolz therefore goes through one helper,
`fitstoolz.utils.open_fits`, which resolves the name to a `pathlib.Path`,
requires it to exist on the local filesystem, and hands astropy the `Path`
rather than the original string. A URL fails the existence check and raises
`FileNotFoundError` before astropy sees it.

It is one helper on purpose. The check used to live at some call sites and not
others, so whether a name was fetched depended on which entry point you came
through; a boundary that holds in one place cannot drift that way.

This is a **"no implicit network access"** guarantee, not a sandbox: a path is
still a path, and fitstoolz will read any file the invoking user can read, and
follow symlinks and network mounts as the filesystem presents them. It has no
notion of a workspace root and does not try to confine you to one.

### Writes are explicit, and `--replace` really does overwrite

`FitsData.write_to_fits` refuses to replace an existing file unless the caller
passes `overwrite=True`; it raises `FileExistsError` otherwise. **The apps all
pass it**, so on the command line a path you name is still a path fitstoolz will
clobber, with no prompt and no backup. The difference is that a library caller
now decides for itself, and can offer its own users a `--no-overwrite` that
means something.

The guard is that there is no default output path. `fitstoolz.apps.outfits_name`
returns a destination only when `--outfile` is given, or when `--replace` is
given (in which case the destination *is* the input file, edited in place). With
neither, the app raises rather than guessing — so overwriting is always
something the caller asked for by name.

Writes are staged through a `.<name>.fitstoolz-tmp` file in the destination
directory and renamed into place. That makes the replacement atomic: a write
that fails part way leaves the previous file intact rather than a truncated one.
It also means the destination briefly needs room for both copies, and that a
crash can leave the temporary behind.

`stack` and `stats` are the exceptions to the shape, not the rule: `stack`
requires `--stacked-fits`, and `stats` writes nothing at all.

### Header edits are data, never code

`fitstoolz header --add/--edit KEY=VALUE` splits on the first `=` and coerces
the right-hand side with `int()`, then `float()`, then falls back to the string
unchanged. There is no expression evaluation and no type inference beyond those
two attempts, so a header value is only ever a number or the literal text you
typed.

### Resource exhaustion is not treated as a vulnerability

A FITS file declaring enormous axes, or a deeply pathological WCS, can make
fitstoolz allocate a lot of memory or take a long time — dask defers the work,
but `da.compute` eventually does it. We treat that as a malformed-input bug to
be fixed on its merits, not as a security boundary: these are command-line tools
run on data you chose to process, not a service accepting files from strangers.
Reports are still welcome; they just aren't embargoed.

## Dependency discipline

Because the parser surface is inherited, keeping the inherited versions honest
is the main ongoing security control:

- **`uv.lock` is committed**, and CI runs every job with `--locked` — so the
  versions tested are the versions a contributor ran, not whatever PyPI
  published that morning.
- **`pip-audit` runs over the locked runtime dependencies** in the `audit` CI
  job and in `.githooks/pre-commit`, using the same two commands in both places,
  so a clean commit and a green job mean the same thing.
- **Dependabot** (`.github/dependabot.yaml`) opens upgrade PRs weekly, moving
  `pyproject.toml` and `uv.lock` together. Dev tooling and runtime minor/patch
  bumps arrive batched; a runtime major — astropy, numpy, pydantic — gets its
  own PR and its own test run. Security updates are enabled repo-side and are
  neither batched nor scheduled.

See `CONTRIBUTING.md` for how to run the audit by hand and what to do about a
finding.

If you find a way around any of the guarantees above, it's a security issue —
please report it as described at the top of this file.
