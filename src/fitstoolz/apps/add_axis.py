from __future__ import annotations

from types import SimpleNamespace

import shinobi
from pydantic import Field

from fitstoolz import set_logger
from fitstoolz.apps import FitsOutputs, outfits_name
from fitstoolz.apps._cli import make_command
from fitstoolz.reader import FitsData

app = "add-axis"


def runit(opts):
    log = set_logger("fitstoolz", level=opts.log_level)
    outfits = outfits_name(opts.fname, opts.outfile, opts.replace, raise_exception=True)

    with FitsData(fname=opts.fname, memmap=True) as myfits:
        if opts.ctype in myfits.coord_names:
            raise ValueError(f"Axis '{opts.ctype}' already exists.")

        myfits.add_axis(
            name=opts.ctype, idx=opts.index, crval=opts.crval, cdelt=opts.cdelt, crpix=opts.crpix, cunit=opts.cunit
        )

        chunks = myfits.build_chunks(
            ra_chunks=opts.ra_chunks, dec_chunks=opts.dec_chunks, spectral_chunks=opts.spectral_chunks
        )
        myfits.write_to_fits(outfits, chunks=chunks)

    log.info(f"Finished. File written to: {outfits}")

    return outfits


@shinobi.pystep(name=app, info="Add an axis to a FITS image")
def add_axis(
    fname: str = Field(..., description="Input file(s)"),
    ctype: str = Field(..., description="Axis type; FREQ, STOKES, etc."),
    index: int = Field(..., description="Add axis at this dimension index"),
    crpix: int = Field(0, description="Reference pixel (zero-based indexing)"),
    crval: float = Field(0.0, description="Value at Reference pixel (crval)"),
    cdelt: float = Field(1.0, description="Pixel width"),
    cunit: str = Field("", description="Units (astropy naming convention)"),
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
step = add_axis

command = make_command(add_axis, positional="fname")
