from __future__ import annotations

from types import SimpleNamespace

import shinobi
from pydantic import Field

from fitstoolz.apps import FitsOutputs
from fitstoolz.apps._cli import make_command

app = "unstack"


def runit(opts):
    raise NotImplementedError("'unstack' is not yet implemented")


@shinobi.pystep(name=app, info="Unstack a FITS image along an axis")
def unstack(
    fname: str = Field(..., description="Input file(s)"),
    axis: str = Field(..., description="Unstack the files along this axis"),
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
step = unstack

command = make_command(unstack, positional="fname")
