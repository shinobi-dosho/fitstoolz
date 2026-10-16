"""Check a wheel installed with its declared dependencies, outside the checkout."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

import fitstoolz
from fitstoolz.apps.main import applist
from fitstoolz.reader import FitsData

checkout = Path(__file__).resolve().parents[1]
assert not Path(fitstoolz.__file__).resolve().is_relative_to(checkout), fitstoolz.__file__
kind = sys.argv[1]
if kind == "base":
    assert importlib.util.find_spec("shinobi") is None
    try:
        importlib.metadata.distribution("stimela-ninja")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError("Base wheel unexpectedly installed stimela-ninja")

cli = str(Path(sys.executable).with_name("fitstoolz"))
subprocess.run([cli, "--help"], check=True)
for name in applist:
    module = importlib.import_module("fitstoolz.apps." + name)
    assert callable(module.runit)
    subprocess.run([cli, name.replace("_", "-"), "--help"], check=True)
    if kind == "ninja":
        public = "slice_" if name == "slice" else name
        assert module.step is getattr(module, public)

with tempfile.TemporaryDirectory(prefix="fitstoolz-wheel-") as directory:
    root = Path(directory)
    image = str(root / "image.fits")
    wcs = WCS(naxis=3)
    wcs.wcs.ctype = ["RA---SIN", "DEC--SIN", "FREQ"]
    wcs.wcs.cdelt = [-0.01, 0.01, 1e6]
    wcs.wcs.crpix = [2, 2, 1]
    wcs.wcs.crval = [15, -31, 1.4e9]
    fits.PrimaryHDU(np.arange(32, dtype=float).reshape(2, 4, 4), wcs.to_header()).writeto(image)
    for args in (
        ["header", image, "--add", "CHECK=1", "--replace"],
        ["stats", image, "--show"],
        ["slice", image, "--axis", "FREQ,0,1", "--outfile", str(root / "slice.fits")],
        ["add-axis", image, "--ctype", "STOKES", "--index", "4", "--crval", "1", "--replace"],
        ["remove-axis", image, "-ct", "STOKES", "-si", "0", "--replace"],
    ):
        subprocess.run([cli, *args], cwd=root, check=True)
    with FitsData(image) as data:
        assert data.ndim == 3
    if kind == "ninja":
        subprocess.run(
            [str(Path(sys.executable).with_name("ninja")), "run", "fitstoolz.apps.stats:stats", "--fname", image],
            cwd=root,
            check=True,
        )
