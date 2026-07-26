from pathlib import Path
from typing import List

from astropy import units
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS


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
    if not fname.exists():
        raise FileNotFoundError(f"Input FITS file '{fname}' does not exist")

    beam_info = {
        "BMAJ": [],
        "BMIN": [],
        "BPA": [],
        "CHAN": [],
        "POL": [],  # set to I for now
    }

    beam_table = None
    # accept the first beam table in hdulist
    with fits.open(fname) as hdulist:
        header = hdulist[0].header
        for hdu in hdulist:
            if isinstance(hdu, fits.BinTableHDU):
                tab = Table.read(hdu)
                if {"BMAJ", "BMIN", "BPA"}.issubset(tab.colnames):
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
