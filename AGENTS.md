# fitstoolz -- design conventions

Read this before adding an app or touching `FitsData`. Most of what follows is
about **axis ordering**, which is where this codebase's bugs come from and what
the library exists to make bearable in the first place.

## Core rule

**Axes have names, and the names are the API.** FITS addresses axes by number
(`NAXIS1`, `CTYPE2`, …), numpy addresses them by position, and the two run in
opposite directions. Nothing outside `FitsData` should have to know that.
Callers say `"FREQ"` or `"RA"`; `FitsData` turns that into whichever index the
layer below wants.

Do not add an API that takes a bare axis integer. If something needs positional
access, it goes through `FitsData.coord_index(name)`.

## Ordering, stated once

`FitsData` stores everything in **numpy order** — slowest-varying axis first —
because that is the order the data array is in:

```python
self.coord_names = self.wcs.axis_type_names[::-1]   # e.g. [STOKES, FREQ, DEC, RA]
self.dim_info    = self.wcs.get_axis_types()[::-1]
```

So the FITS keyword for python-order index `idx` is `NAXIS{self.ndim - idx}`,
and that `self.ndim - idx` expression is all over `reader.py`. It is not an
off-by-one waiting to happen; it is the conversion. When you write a new one,
write it the same way rather than inventing a local variant.

Two related conventions:

- **`CRPIX` is 1-based on disk, 0-based in memory.** Every read subtracts one
  (`ref_pixel`), every write adds it back (`crpix + 1`). Both directions live in
  `set_coord_attrs` and `write_to_fits`; keep them there.
- **`coord_names` are FITS axis names; `dims` are xarray dimension labels.**
  They are not the same vocabulary — `"RA"` is a coord name, `"celestial.ra"` is
  its dim. Anything user-facing accepts coord names and translates
  (`get_xds` does this for both `chunks` and `transpose`).

## Coordinates are evaluated through the WCS, not stepped by CDELT

`set_celestial_dimensions` samples each celestial axis by calling
`wcs_pix2world` through the *other* axis's reference pixel. Do not "simplify"
this into `crval + cdelt * arange(n)`.

The sky is not separable under a projection: a pixel's longitude depends on its
latitude. `CDELT` is an angle on the sky, so stepping longitude by it is wrong by
`1/cos(dec)`. The comment in `set_celestial_dimensions` says this too — it is
there because the wrong version looks more obviously correct than the right one.

Spectral axes go through `wcs.spectral.array_index_to_world_values` for the same
reason. Stokes is the one axis built arithmetically, because it genuinely is a
labelled integer sequence.

An axis astropy cannot classify (`coordinate_type is None` — a linear or blank
`CTYPE`) falls back to pixel indices. That fallback is deliberate: an
unrecognised axis should still be addressable, not fatal.

## Data stays lazy

`FitsData.data` is a dask array and reductions are dask reductions. Call
`da.compute` **once**, as late as possible, and for everything you need at the
same time — `stats.runit` computes min/max/mean/std in a single call precisely so
the four outputs cost one pass rather than four.

`memmap=True` is the default on the way in. Don't materialise a cube to work out
its shape or dtype; the header already knows.

That rule binds the reader itself, and it is easy to break by accident.
`FitsData.data` is built by `map_blocks` over `reader.read_block`, which opens
the file and reads *its own slice* through `HDU.section` when the block is
computed. It is not `da.asarray(hdu.data)` — that reads the whole cube at
construction whatever it is chunked to afterwards, which caps the package at
cubes that fit in RAM. Nor is it `da.from_array(hdu.data)`: handed a memmap,
dask materialises that too, `name=False` included. `tests/test_reader.py`
guards this by asserting the serialised graph stays a few kilobytes as the cube
grows, which is what fails if the data ends up embedded in it.

Chunking comes from `utils.contiguous_chunks`, which splits the *slowest*-varying
axes and keeps the trailing ones whole, because FITS stores `NAXIS1` fastest and
that is the axis order a contiguous read follows. Callers who want a different
shape — RA blocks, say — rechunk through `get_xds`; the reader does not try to
guess the access pattern.

## Beams: what the file recorded, not what we modelled

`FitsData.beam_table` mixes two things, and only one of them may be written back.
Beams read from a `BinTableHDU` are *data*: `beam_table_extname` records which
extension they came from, and `write_to_fits` writes them back there. Beams read
from `BMAJ`/`BMIN`/`BPA` keywords are already carried by the header copy, and
`__register_beam_table` expanding a single one of those over frequency is a
model of ours — emitting it as a table would promote that model to something the
file claims to have measured. Hence the rule: write a beam extension only when
`beam_table_extname` is set.

Rows follow the data. A spectral `data_slice` cuts the table, `regrid_axis`
interpolates it onto the new grid, and a `CHAN` column is renumbered against the
output. A table that does not have one row per channel describes the cube as a
whole and is left alone.

## Two unit systems, and the line between them

This is the single richest source of bugs in the package, because every one of
them is invisible on a cube whose `CUNIT` is already SI — which is most of them.

There are two unit systems in play and they are **not** the same:

- **Header units** — what `CRVAL`, `CDELT` and `CUNIT` are written in, and what
  `coords[...].pixel_size` (straight off `CDELT`) carries.
- **World units** — what `coords[...]` values and `world_axis_units` report.
  astropy normalises a spectral axis to SI here regardless of `CUNIT`, so a cube
  in MHz has a header in MHz and a grid in Hz.

The rule: **never mix a value from one system with a value from the other.**
Three separate bugs came from doing exactly that, and all three shipped:

- `expand_along_axis` stepped the grid by `pixel_size` (header) to extend a grid
  in world units, so stacking two MHz cubes appended channels 1 Hz apart and
  piled them on top of each other.
- `write_to_fits` wrote `CUNIT` from `world_axis_units` while `CDELT` came from
  the header, describing an MHz cube as a Hz one with its MHz channel width.
  `to_unit` now converts `CRVAL` into whichever unit `CUNIT` claims.
- `regrid_axis` takes `values` in header units, so its beam interpolation reads
  *both* grids off `coords` rather than comparing against `values`.

When you need a spacing, prefer differencing the coordinate grid over reading
`CDELT`: it is in the same system as everything else you are holding. When you
write a header, convert explicitly and say which way you are going.

## One lazy constructor

`reader.lazy_data(fname, hdu)` is the only place a dask array is built over an
HDU, and both `FitsData.__init__` and `expand_along_axis_from_files` go through
it. There were two `da.asarray(hdu.data)` call sites and each had to be found
separately; keep it to one.

## Apps: one module, one pystep, four names

Every module in `src/fitstoolz/apps/` follows the same shape, and the CLI relies
on it:

```python
app = "stack"                                  # subcommand name

class StackOutputs(BaseModel): ...             # typed outputs (optional but preferred)

def runit(opts): ...                           # plain function, takes a namespace

@shinobi.pystep(name=app, info="...")
def stack(fname: str = Field(...), ...) -> StackOutputs:
    opts = SimpleNamespace(**locals())
    return StackOutputs(stacked_fits=runit(opts))

step = stack                                   # uniform handle
command = make_command(stack, positional="fname")
```

- **The pystep signature is the single schema authority.** Click options are
  generated from the pydantic model by `shinobi.clickutil.build_options`. There
  are no YAML parameter files — those were removed when the CLI moved off scabha,
  and re-adding a parallel schema is exactly the regression to avoid. If an
  option needs a description, a default, or a choice list, it goes on the
  `Field`.
- **`runit` is a plain function**, not a `click.Command`. That keeps the real
  work importable and testable without click's runner in the way.
- **`step` and `command` are uniform names** so a caller — the CLI group, a test,
  a downstream shinobi recipe or dosho tool — can find them without knowing the
  function's own name.
- **Outputs are a pydantic model**, so a following recipe step can be wired to
  `stacked_fits` or `std` rather than re-deriving it from a filename convention.

### Registering a new app

Add its name to `applist` in `apps/main.py`. That list is also a security
boundary: `LazyClickGroup` resolves subcommands through `importlib`, and it may
only ever do so against that hardcoded table (see `SECURITY.md`). Never build the
import path from user input.

The laziness is worth preserving — it's why `fitstoolz --help` doesn't import
dask, xarray and astropy — so keep module-level work in an app to the pystep
declaration itself.

## Opening files

**Always `fitstoolz.utils.open_fits`, never `astropy.io.fits.open`.**

`fits.open` fetches a string that looks like a URL. `open_fits` requires the path
to exist locally and hands astropy a `Path`, which is the whole of the "filenames
are paths, never URLs" guarantee in `SECURITY.md`. That guarantee is only worth
stating because there is one door; a second call site is a hole, not a shortcut.

The check used to be duplicated at some call sites and missing at others, which
is how it came to be a helper.

## Writing files

Writes pass `overwrite=True`, so a destination is always clobbered. The
compensating rule is that **there is no default destination**:
`apps.outfits_name` returns a path only for `--outfile` or `--replace`, and
raises otherwise. Keep it that way — an app that invents an output filename can
silently destroy an input.

## Don't add

- **An axis-order configuration option.** The order is numpy's, internally, and
  FITS's, on disk. A third choice is a bug generator.
- **A second schema format.** Parameters are pydantic `Field`s on the pystep.
- **Eager `.compute()` in `FitsData`.** Reductions belong to the caller.
- **A parallel FITS reader.** `FitsData` is the reader; apps use it. `header` is
  the one app that touches `astropy.io.fits` structures directly, because it
  edits header cards rather than data.

## Reviewing changes: check the tree, not just the diff

A claim that something "doesn't exist" or "is unused" should be verified against
the actual tree before acting on it — a symbol absent from the diff is usually
present in the repo.
