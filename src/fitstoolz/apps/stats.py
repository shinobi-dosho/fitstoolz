from __future__ import annotations

from types import SimpleNamespace

import dask.array as da
import numpy as np
import shinobi
from pydantic import BaseModel, Field

from fitstoolz import set_logger
from fitstoolz.apps._cli import make_command
from fitstoolz.reader import FitsData

app = "stats"


class StatsOutputs(BaseModel):
    """Image statistics, so a following step can branch on them."""

    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None


def runit(opts):
    log = set_logger("fitstoolz", level=opts.log_level)

    with FitsData(fname=opts.fname, memmap=True) as myfits:
        data = myfits.data

        slc = [slice(None)] * myfits.ndim
        if opts.slice:
            for axspec in opts.slice:
                ctype, start, end = str(axspec).split(",")
                start = int(start)
                end = int(end)
                if ctype not in myfits.coord_names:
                    raise ValueError(f"Unknown axis '{ctype}'. Existing axes are: {myfits.coord_names}")
                idx = myfits.coord_names.index(ctype)
                slc[idx] = slice(start, end)
        data = data[tuple(slc)]

        if opts.clip_below is not None:
            blank = opts.blank_value if opts.blank_value is not None else np.nan
            data = da.where(data < opts.clip_below, blank, data)
        if opts.clip_above is not None:
            blank = opts.blank_value if opts.blank_value is not None else np.nan
            data = da.where(data > opts.clip_above, blank, data)

        # One pass over the data for all four reductions, so the returned
        # outputs cost no more than the single statistic that gets logged.
        dmin, dmax, dmean, dstd = da.compute(data.min(), data.max(), data.mean(), data.std())

        if opts.show:
            log.info(f"min={dmin:.6g}  max={dmax:.6g}  mean={dmean:.6g}  std={dstd:.6g}")
        else:
            log.info(f"Data standard deviation: {dstd}")

    return StatsOutputs(min=float(dmin), max=float(dmax), mean=float(dmean), std=float(dstd))


@shinobi.pystep(name=app, info="Get image statistics")
def stats(
    fname: str = Field(..., description="Input file(s)"),
    show: bool = Field(False, description="Show min, max, mean and standard deviation"),
    slice: list[str] | None = Field(None, description="Slice data, as CTYPE,START,END"),
    clip_below: float | None = Field(None, description="Blank pixels below this value"),
    clip_above: float | None = Field(None, description="Blank pixels above this value"),
    blank_value: float | None = Field(
        None,
        description="Blank value when using --clip-below/above. The values 'inf' and 'nan' are valid blank values.",
    ),
    log_level: str = Field("INFO", description="Log level"),
) -> StatsOutputs:
    opts = SimpleNamespace(**locals())
    return runit(opts)


#: Uniform handle for this module's pystep, so the StepRef can be looked up
#: generically (by the CLI group, tests, or a downstream shinobi/dosho caller)
#: without knowing the function's own name.
step = stats

command = make_command(stats, positional="fname")
