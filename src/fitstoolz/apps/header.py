from __future__ import annotations

from types import SimpleNamespace

import click
from pydantic import Field

from fitstoolz.apps import FitsOutputs
from fitstoolz.apps._cli import inputs_from_signature, make_command, optional_step
from fitstoolz.utils import open_fits

app = "header"


def runit(opts):
    if opts.show:
        with open_fits(opts.fname) as hdul:
            # The header dump is this command's product, not a log line, so it
            # goes to stdout on its own -- pipe `header --show` into grep and
            # you get the header, not the logger's timestamps.
            click.echo(repr(hdul[0].header))
        return None

    outfile = None
    if opts.outfile:
        outfile = opts.outfile
    elif opts.replace:
        outfile = opts.fname

    if outfile is None:
        raise RuntimeError("Neither --replace nor --outfile is set. Cannot add/remove/edit.")

    updates = {}
    hdul = open_fits(opts.fname)

    if opts.edit or opts.add:
        if opts.edit:
            keyvals = opts.edit
        else:
            keyvals = opts.add

        for keyval in keyvals:
            key, strval = keyval.split("=", 1)
            key = key.strip()
            strval = strval.strip()

            try:
                val = int(strval)
            except ValueError:
                try:
                    val = float(strval)
                except ValueError:
                    val = strval

            updates[key] = val
        hdul[0].header.update(updates)

    elif opts.remove:
        for key in opts.remove:
            del hdul[0].header[key]

    hdul.writeto(outfile, overwrite=True)

    hdul.close()

    return outfile


def _header(
    fname: str = Field(..., description="Input file(s)"),
    show: bool = Field(False, description="Show header and exit"),
    edit: list[str] | None = Field(None, description="Edit FITS header entry, as KEY=VALUE"),
    remove: list[str] | None = Field(None, description="Remove header entry"),
    add: list[str] | None = Field(None, description="Add header entry, as KEY=VALUE"),
    outfile: str | None = Field(None, description="Path of output image"),
    replace: bool = Field(False, description="Overwrite output if it exists"),
    log_level: str = Field("INFO", description="Log level"),
) -> FitsOutputs:
    opts = SimpleNamespace(**locals())
    return FitsOutputs(outfile=runit(opts))


inputs_model = inputs_from_signature(_header)
INFO = "Show, add, edit or remove FITS header entries"
command = make_command(_header, name=app, info=INFO, model=inputs_model, positional="fname")


def __getattr__(name):
    if name in ("header", "step"):
        adapter = optional_step(_header, name=app, info=INFO)
        globals()["header"] = globals()["step"] = adapter
        return adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
