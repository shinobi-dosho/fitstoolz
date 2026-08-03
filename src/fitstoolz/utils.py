from pathlib import Path
from typing import List, Tuple

import dask
import numpy as np
from astropy import units
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS
from dask.utils import parse_bytes


def open_fits(fname, **kwargs) -> fits.HDUList:
    """Open a local FITS file.

    Every FITS read in fitstoolz goes through here, so the "filenames are paths,
    never URLs" boundary in ``SECURITY.md`` holds in one place instead of being
    re-derived at each call site.

    ``astropy.io.fits.open`` treats a string that looks like a URL as something
    to fetch (via ``astropy.utils.data.download_file``), so an unchecked name
    turns a filename argument into an outbound network request. Requiring the
    path to exist rejects that, and passing astropy a ``Path`` rather than the
    original string means it never gets to make the judgement itself.

    Args:
        fname (str|Path): Path to a FITS file on the local filesystem.
        **kwargs: Passed through to ``astropy.io.fits.open`` (``memmap``, etc).

    Returns:
        astropy.io.fits.HDUList: The opened file.

    Raises:
        FileNotFoundError: If no such path exists locally.
    """
    path = Path(fname)
    if not path.exists():
        raise FileNotFoundError(f"Input FITS file '{fname}' does not exist")
    return fits.open(path, **kwargs)


def contiguous_chunks(shape: Tuple[int, ...], dtype, limit=None) -> Tuple[int, ...]:
    """Chunk shape that splits a FITS array along its slowest-varying axes.

    FITS stores ``NAXIS1`` fastest-varying, which is the *last* axis in numpy
    order, so a chunk that keeps the trailing axes whole is a contiguous run of
    bytes on disk. Chunking the other way round -- along RA, say -- makes every
    chunk a scatter-read over the whole file. The reader therefore chunks for the
    file layout rather than guessing an access pattern; a caller who wants RA
    blocks asks for them through ``FitsData.get_xds``.

    Trailing axes are kept whole for as long as they fit within ``limit``. The
    first axis that does not fit is split, and every axis slower than it is
    chunked to one element.

    Args:
        shape (tuple): Array shape, in numpy (C) order.
        dtype: Element type, or anything ``numpy.dtype`` accepts.
        limit (int|str, optional): Largest chunk in bytes, or a string such as
            ``'128MiB'``. Defaults to dask's own ``array.chunk-size``.

    Returns:
        tuple: Chunk length per axis, ready to hand to dask as ``chunks=``.
    """
    itemsize = np.dtype(dtype).itemsize
    limit = parse_bytes(limit if limit is not None else dask.config.get("array.chunk-size"))

    chunks = list(shape)
    trailing = itemsize
    for axis in range(len(shape) - 1, -1, -1):
        if trailing * shape[axis] > limit:
            # The array stops fitting at this axis. Split it, and take the axes
            # slower still one element at a time.
            chunks[axis] = max(1, limit // trailing)
            for slower in range(axis):
                chunks[slower] = 1
            break
        trailing *= shape[axis]

    return tuple(chunks)


def reorder_wcs(wcs, old_order: List[str], new_order: List[str]) -> WCS:
    """Reorder wcs axes

    Args:
        wcs (astropy.wcs.WCS): WCS object to reorder
        old_order (List[str]): Old order
        new_order (List[str]): New order

    Returns:
        astropy.wcs.WCS: Reordered WCS
    """
    wcs_keys = "crval crpix cdelt cunit ctype".split()
    new_wcs = WCS(naxis=wcs.naxis)

    for key in wcs_keys:
        for ndx, axis in enumerate(new_order):
            odx = old_order.index(axis)
            getattr(new_wcs.wcs, key)[ndx] = getattr(wcs.wcs, key)[odx]

    return new_wcs


def beam_unit(header) -> units.Unit:
    """
    Unit of the BMAJ/BMIN/BPA header keywords.

    These are angles, conventionally in degrees. The first axis' CUNIT is only
    honoured when it is itself an angle, since a cube may lead with a spectral
    or Stokes axis.
    """
    cunit = str(header.get("CUNIT1", "")).strip()
    if cunit:
        try:
            unit = units.Unit(cunit)
        except ValueError:
            unit = None
        if unit is not None and unit.physical_type == "angle":
            return unit
    return units.deg


def get_beam_table(fname: Path):
    fname = Path(fname)

    beam_info = {
        "BMAJ": [],
        "BMIN": [],
        "BPA": [],
        "CHAN": [],
        "POL": [],  # set to I for now
    }

    beam_table = None
    # accept the first beam table in hdulist
    with open_fits(fname) as hdulist:
        header = hdulist[0].header
        for hdu in hdulist:
            if isinstance(hdu, fits.BinTableHDU):
                tab = Table.read(hdu)
                if {"BMAJ", "BMIN", "BPA"}.issubset(tab.colnames):
                    # Record which extension it came from. This is the flag that
                    # tells a writer the beams live in an HDU of their own rather
                    # than in BMAJ/BMIN/BPA header keywords -- and so whether
                    # writing an HDU back preserves the input or invents an
                    # extension the input never had.
                    tab.meta.setdefault("EXTNAME", hdu.name or "BEAMS")
                    beam_table = tab
                    break

    if isinstance(beam_table, Table):
        return beam_table

    if header.get("BMAJ1", None) is None and header.get("BMAJ", None) is None:
        return False

    bunit = beam_unit(header)
    chan = 1

    while header.get(f"BMAJ{chan}", None) is not None:
        beam_info["BMAJ"].append(header[f"BMAJ{chan}"] * bunit)
        beam_info["BMIN"].append(header[f"BMIN{chan}"] * bunit)
        beam_info["BPA"].append(header[f"BPA{chan}"] * bunit)
        beam_info["CHAN"].append(chan - 1)
        beam_info["POL"].append(0)
        chan += 1

    if chan == 1 and header.get("BMAJ", None) is not None:
        beam_info["BMAJ"].append(header["BMAJ"] * bunit)
        beam_info["BMIN"].append(header["BMIN"] * bunit)
        beam_info["BPA"].append(header["BPA"] * bunit)
        beam_info["CHAN"].append(0)
        beam_info["POL"].append(0)

        chan = 2

    if chan > 1:
        return Table(beam_info)
    else:
        return False
