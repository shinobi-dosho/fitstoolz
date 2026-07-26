from __future__ import annotations

from types import SimpleNamespace

import click
import shinobi
from pydantic import Field

from fitstoolz.apps import FitsOutputs
from fitstoolz.apps._cli import make_command
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


@shinobi.pystep(name=app, info="Show, add, edit or remove FITS header entries")
def header(
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


#: Uniform handle for this module's pystep, so the StepRef can be looked up
#: generically (by the CLI group, tests, or a downstream shinobi/dosho caller)
#: without knowing the function's own name.
step = header

command = make_command(header, positional="fname")
