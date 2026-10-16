from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, Field

from fitstoolz import LOGGER
from fitstoolz.apps._cli import inputs_from_signature, make_command, optional_step
from fitstoolz.reader import FitsData

app = "unstack"


class UnstackOutputs(BaseModel):
    """Output paths in increasing pixel order along the split axis."""

    unstacked_fits: list[str]


def runit(opts):
    prefix = opts.output_prefix
    if prefix.lower().endswith(".fits"):
        prefix = prefix[:-5]
    if not prefix or not Path(prefix).name:
        raise ValueError("output_prefix must include a filename stem")

    source = Path(opts.fname)
    log = logging.getLogger(LOGGER)
    with FitsData(fname=opts.fname, memmap=True) as myfits:
        idx = myfits.coord_index(opts.axis)
        count = myfits.dshape[idx]
        width = max(4, len(str(count - 1)))
        outputs = [f"{prefix}-{pixel:0{width}d}.fits" for pixel in range(count)]

        # Each lazy write reopens the source. Reject every alias before writing
        # anything, including a later output that would replace the source.
        for output in outputs:
            destination = Path(output)
            if destination.resolve() == source.resolve() or (destination.exists() and destination.samefile(source)):
                raise ValueError(f"Unstack output would overwrite the input file: {output}")

        chunks = myfits.build_chunks(
            ra_chunks=opts.ra_chunks, dec_chunks=opts.dec_chunks, spectral_chunks=opts.spectral_chunks
        )
        selection = [slice(None)] * myfits.ndim
        for pixel, output in enumerate(outputs):
            selection[idx] = slice(pixel, pixel + 1)
            myfits.write_to_fits(output, data_slice=selection, chunks=chunks, overwrite=True)
            log.info("Wrote unstacked file to: %s", output)

    return outputs


def _unstack(
    fname: str = Field(..., description="Input FITS image"),
    axis: str = Field(..., description="Named axis to split into length-one planes (e.g. FREQ or STOKES)"),
    output_prefix: str = Field(
        ...,
        min_length=1,
        description="Output path stem; writes PREFIX-0000.fits, etc., overwriting existing outputs. "
        "A trailing .fits is stripped",
    ),
    ra_chunks: int | None = Field(None, description="RA chunking"),
    dec_chunks: int | None = Field(None, description="Dec chunking"),
    spectral_chunks: int | None = Field(None, description="Spectral chunking"),
    log_level: str = Field("INFO", description="Log level"),
) -> UnstackOutputs:
    opts = SimpleNamespace(**locals())
    return UnstackOutputs(unstacked_fits=runit(opts))


inputs_model = inputs_from_signature(_unstack)
INFO = "Unstack a FITS image along an axis"
command = make_command(_unstack, name=app, info=INFO, model=inputs_model, positional="fname")


def __getattr__(name):
    if name in ("unstack", "step"):
        adapter = optional_step(_unstack, name=app, info=INFO)
        globals()["unstack"] = globals()["step"] = adapter
        return adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
