from __future__ import annotations

import logging
from types import SimpleNamespace

from pydantic import Field

from fitstoolz import LOGGER
from fitstoolz.apps import FitsOutputs, outfits_name
from fitstoolz.apps._cli import inputs_from_signature, make_command, optional_step
from fitstoolz.reader import FitsData

app = "remove-axis"


def runit(opts):
    log = logging.getLogger(LOGGER)
    outfits = outfits_name(opts.fname, opts.outfile, opts.replace, raise_exception=True)

    with FitsData(fname=opts.fname, memmap=True) as myfits:
        coord_names = list(myfits.coord_names)
        if opts.ctype not in coord_names:
            raise ValueError(f"Unknown axis '{opts.ctype}'. Existing axes are: {coord_names}")

        idx = coord_names.index(opts.ctype)
        coord_names.pop(idx)
        slc = [slice(None)] * myfits.ndim
        slc[idx] = opts.select_index

        chunks = myfits.build_chunks(
            ra_chunks=opts.ra_chunks, dec_chunks=opts.dec_chunks, spectral_chunks=opts.spectral_chunks
        )
        myfits.write_to_fits(outfits, coord_names=coord_names, data_slice=slc, chunks=chunks, overwrite=True)

    log.info("Finished. File written to: %s", outfits)

    return outfits


def _remove_axis(
    fname: str = Field(..., description="Input file(s)"),
    ctype: str = Field(
        ...,
        description="Axis type (or dimension). FREQ, STOKES, etc.",
        json_schema_extra={"abbreviation": "ct"},
    ),
    select_index: int = Field(
        0,
        description="Keep data at this index (zero-based). For example, if removing the frequency axis, "
        "this would be the channel to keep.",
        json_schema_extra={"abbreviation": "si"},
    ),
    ra_chunks: int | None = Field(None, description="RA chunking"),
    dec_chunks: int | None = Field(None, description="Dec chunking"),
    spectral_chunks: int | None = Field(None, description="Spectral chunking"),
    outfile: str | None = Field(None, description="Path of output image"),
    replace: bool = Field(False, description="Overwrite output if it exists"),
    log_level: str = Field("INFO", description="Log level"),
) -> FitsOutputs:
    opts = SimpleNamespace(**locals())
    return FitsOutputs(outfile=runit(opts))


inputs_model = inputs_from_signature(_remove_axis)
INFO = "Remove an axis from a FITS image"
command = make_command(_remove_axis, name=app, info=INFO, model=inputs_model, positional="fname")


def __getattr__(name):
    if name in ("remove_axis", "step"):
        adapter = optional_step(_remove_axis, name=app, info=INFO)
        globals()["remove_axis"] = globals()["step"] = adapter
        return adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
