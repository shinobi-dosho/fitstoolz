from __future__ import annotations

import logging
from types import SimpleNamespace

from pydantic import BaseModel, Field

from fitstoolz import LOGGER
from fitstoolz.apps._cli import inputs_from_signature, make_command, optional_step
from fitstoolz.reader import FitsData

app = "stack"


class StackOutputs(BaseModel):
    """Path of the stacked FITS file."""

    stacked_fits: str | None = None


def runit(opts):
    log = logging.getLogger(LOGGER)

    fname0 = opts.fname
    fnames = opts.extra_files or []

    with FitsData(fname=fname0, memmap=True) as myfits:
        myfits.expand_along_axis_from_files(opts.axis, fnames)
        chunks = myfits.build_chunks(
            ra_chunks=opts.ra_chunks, dec_chunks=opts.dec_chunks, spectral_chunks=opts.spectral_chunks
        )
        myfits.write_to_fits(opts.stacked_fits, chunks=chunks, overwrite=True)

    log.info("Wrote stacked file to: %s", opts.stacked_fits)

    return opts.stacked_fits


def _stack(
    fname: str = Field(..., description="Input file(s)"),
    axis: str = Field(..., description="Stack files along this axis"),
    extra_files: list[str] | None = Field(None, description="Additional files to stack (use multiple times)"),
    stacked_fits: str = Field(..., description="Path of stacked output image"),
    ra_chunks: int | None = Field(None, description="RA chunking"),
    dec_chunks: int | None = Field(None, description="Dec chunking"),
    spectral_chunks: int | None = Field(None, description="Spectral chunking"),
    log_level: str = Field("INFO", description="Log level"),
) -> StackOutputs:
    opts = SimpleNamespace(**locals())
    return StackOutputs(stacked_fits=runit(opts))


inputs_model = inputs_from_signature(_stack)
INFO = "Stack FITS images along an axis"
command = make_command(_stack, name=app, info=INFO, model=inputs_model, positional="fname")


def __getattr__(name):
    if name in ("stack", "step"):
        adapter = optional_step(_stack, name=app, info=INFO)
        globals()["stack"] = globals()["step"] = adapter
        return adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
