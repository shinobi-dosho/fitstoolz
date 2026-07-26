from __future__ import annotations

from types import SimpleNamespace

import shinobi
from pydantic import BaseModel, Field

from fitstoolz import set_logger
from fitstoolz.apps._cli import make_command
from fitstoolz.reader import FitsData

app = "stack"


class StackOutputs(BaseModel):
    """Path of the stacked FITS file."""

    stacked_fits: str | None = None


def runit(opts):
    log = set_logger("fitstoolz", level=opts.log_level)

    fname0 = opts.fname
    fnames = opts.extra_files or []

    with FitsData(fname=fname0, memmap=True) as myfits:
        myfits.expand_along_axis_from_files(opts.axis, fnames)
        chunks = myfits.build_chunks(
            ra_chunks=opts.ra_chunks, dec_chunks=opts.dec_chunks, spectral_chunks=opts.spectral_chunks
        )
        myfits.write_to_fits(opts.stacked_fits, chunks=chunks)

    log.info(f"Wrote stacked file to: {opts.stacked_fits}")

    return opts.stacked_fits


@shinobi.pystep(name=app, info="Stack FITS images along an axis")
def stack(
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


#: Uniform handle for this module's pystep, so the StepRef can be looked up
#: generically (by the CLI group, tests, or a downstream shinobi/dosho caller)
#: without knowing the function's own name.
step = stack

command = make_command(stack, positional="fname")
