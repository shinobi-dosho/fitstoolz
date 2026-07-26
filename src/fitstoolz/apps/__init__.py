from __future__ import annotations

from pydantic import BaseModel


class FitsOutputs(BaseModel):
    """Path of the FITS file an app wrote, so it can be wired into a shinobi
    Recipe (or consumed as a dosho tool) as the input of a following step."""

    outfile: str | None = None


def outfits_name(infile, outfile, replace=False, raise_exception=False):
    if outfile:
        return outfile
    elif replace:
        return infile
    else:
        if raise_exception:
            raise RuntimeError("Both --replace and --outfile are not set. Cannot modify FITS file(s).")
        else:
            return None
