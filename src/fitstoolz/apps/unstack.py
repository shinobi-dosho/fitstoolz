from __future__ import annotations

from types import SimpleNamespace

from pydantic import Field

from fitstoolz.apps import FitsOutputs
from fitstoolz.apps._cli import inputs_from_signature, make_command, optional_step

app = "unstack"


def runit(opts):
    raise NotImplementedError("'unstack' is not yet implemented")


def _unstack(
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


inputs_model = inputs_from_signature(_unstack)
INFO = "Unstack a FITS image along an axis"
command = make_command(_unstack, name=app, info=INFO, model=inputs_model, positional="fname")


def __getattr__(name):
    if name in ("unstack", "step"):
        adapter = optional_step(_unstack, name=app, info=INFO)
        globals()["unstack"] = globals()["step"] = adapter
        return adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
