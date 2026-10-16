from __future__ import annotations

from types import SimpleNamespace

from pydantic import Field

from fitstoolz.apps import FitsOutputs, outfits_name
from fitstoolz.apps._cli import inputs_from_signature, make_command, optional_step
from fitstoolz.reader import FitsData

app = "slice"


def runit(opts):
    outfits = outfits_name(opts.fname, opts.outfile, replace=opts.replace, raise_exception=True)

    with FitsData(fname=opts.fname, memmap=opts.memmap) as myfits:
        coord_names = list(myfits.coord_names)
        slc = [slice(None)] * myfits.ndim

        if opts.axis:
            for axspec in opts.axis:
                ctype, start, end = str(axspec).split(",")
                start = int(start)
                end = int(end)
                if ctype not in coord_names:
                    raise ValueError(f"Unknown axis '{ctype}'. Existing axes are: {coord_names}")
                idx = coord_names.index(ctype)
                slc[idx] = slice(start, end)

        chunks = myfits.build_chunks(
            ra_chunks=opts.ra_chunks, dec_chunks=opts.dec_chunks, spectral_chunks=opts.spectral_chunks
        )
        myfits.write_to_fits(outfits, coord_names=coord_names, data_slice=slc, chunks=chunks, overwrite=True)

    return outfits


def _slice(
    fname: str = Field(..., description="Input file(s)"),
    axis: list[str] | None = Field(None, description="Axis slicing info, as CTYPE,START,END"),
    memmap: bool = Field(True, description="memmap option to pass to astropy.io.fits.open()"),
    ra_chunks: int | None = Field(None, description="RA chunking"),
    dec_chunks: int | None = Field(None, description="Dec chunking"),
    spectral_chunks: int | None = Field(None, description="Spectral chunking"),
    outfile: str | None = Field(None, description="Path of output image"),
    replace: bool = Field(False, description="Overwrite output if it exists"),
    log_level: str = Field("INFO", description="Log level"),
) -> FitsOutputs:
    opts = SimpleNamespace(**locals())
    return FitsOutputs(outfile=runit(opts))


inputs_model = inputs_from_signature(_slice)
INFO = "Slice a FITS image along one or more axes"
command = make_command(_slice, name=app, info=INFO, model=inputs_model, positional="fname")


def __getattr__(name):
    if name in ("slice_", "step"):
        adapter = optional_step(_slice, name=app, info=INFO)
        globals()["slice_"] = globals()["step"] = adapter
        return adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
