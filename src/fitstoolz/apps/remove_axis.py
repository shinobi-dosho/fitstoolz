from __future__ import annotations

from types import SimpleNamespace

import shinobi
from pydantic import Field

from fitstoolz import set_logger
from fitstoolz.apps import FitsOutputs, outfits_name
from fitstoolz.apps._cli import make_command
from fitstoolz.reader import FitsData

app = "remove-axis"


def runit(opts):
    log = set_logger("fitstoolz", level=opts.log_level)
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
        myfits.write_to_fits(outfits, coord_names=coord_names, data_slice=slc, chunks=chunks)

    log.info(f"Finished. File written to: {outfits}")

    return outfits


@shinobi.pystep(name=app, info="Remove an axis from a FITS image")
def remove_axis(
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


#: Uniform handle for this module's pystep, so the StepRef can be looked up
#: generically (by the CLI group, tests, or a downstream shinobi/dosho caller)
#: without knowing the function's own name.
step = remove_axis

command = make_command(remove_axis, positional="fname")
