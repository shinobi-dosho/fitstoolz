"""Tests for the celestial coordinate grids built by FitsData.

astropy's WCS is the reference throughout: the grids must reproduce
``wcs_pix2world`` along each principal axis.
"""

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from fitstoolz.reader import FitsData

from . import InitTest


@pytest.fixture
def config():
    return InitTest()


def write_image(config, naxis1, naxis2, crval1, crval2, cdelt, ndim=2, ctype="SIN"):
    """A FITS image with the usual negative CDELT1 (RA decreasing with pixel index)."""
    shape = (naxis2, naxis1) if ndim == 2 else (1, 1, naxis2, naxis1)
    header = fits.Header()
    header["CTYPE1"] = f"RA---{ctype}"
    header["CRVAL1"] = crval1
    header["CDELT1"] = -cdelt
    header["CRPIX1"] = naxis1 // 2 + 1
    header["CUNIT1"] = "deg"
    header["CTYPE2"] = f"DEC--{ctype}"
    header["CRVAL2"] = crval2
    header["CDELT2"] = cdelt
    header["CRPIX2"] = naxis2 // 2 + 1
    header["CUNIT2"] = "deg"
    if ndim == 4:
        for key, value in {
            "CTYPE3": "FREQ",
            "CRVAL3": 1.4e9,
            "CDELT3": 1e6,
            "CRPIX3": 1,
            "CUNIT3": "Hz",
            "CTYPE4": "STOKES",
            "CRVAL4": 1,
            "CDELT4": 1,
            "CRPIX4": 1,
        }.items():
            header[key] = value
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros(shape), header=header).writeto(path, overwrite=True)
    return path, header


def astropy_axis_grids(header, naxis1, naxis2):
    """Reference grids: each axis sampled through the other's reference pixel."""
    wcs = WCS(header).celestial
    ref1, ref2 = header["CRPIX1"] - 1, header["CRPIX2"] - 1
    ra = wcs.wcs_pix2world(np.column_stack([np.arange(naxis1), np.full(naxis1, ref2)]), 0)[:, 0]
    dec = wcs.wcs_pix2world(np.column_stack([np.full(naxis2, ref1), np.arange(naxis2)]), 0)[:, 1]
    return ra, dec


@pytest.mark.parametrize("crval2", [0.0, -31.0, 70.0], ids=["equator", "dec-31", "dec+70"])
@pytest.mark.parametrize("naxis", [64, 65], ids=["even", "odd"])
def test_celestial_grids_match_astropy(config, crval2, naxis):
    path, header = write_image(config, naxis, naxis, 15.0, crval2, 20.0 / 3600)
    fds = FitsData(path)

    ra_expected, dec_expected = astropy_axis_grids(header, naxis, naxis)
    np.testing.assert_allclose(np.squeeze(fds.coords["RA"].data), ra_expected, rtol=0, atol=1e-12)
    np.testing.assert_allclose(np.squeeze(fds.coords["DEC"].data), dec_expected, rtol=0, atol=1e-12)


def test_reference_pixel_carries_the_reference_value(config):
    """The grid must pass exactly through CRVAL at CRPIX."""
    n, crval1, crval2 = 64, 15.0, -31.0
    path, header = write_image(config, n, n, crval1, crval2, 20.0 / 3600)
    fds = FitsData(path)
    ra = np.squeeze(fds.coords["RA"].data)
    dec = np.squeeze(fds.coords["DEC"].data)
    assert ra[header["CRPIX1"] - 1] == pytest.approx(crval1, abs=1e-12)
    assert dec[header["CRPIX2"] - 1] == pytest.approx(crval2, abs=1e-12)


def test_declination_step_follows_cdelt2_not_cdelt1(config):
    """Regression: dec_scale used to read CDELT1, so DEC ran backwards."""
    cell = 20.0 / 3600
    path, _ = write_image(config, 64, 64, 15.0, -31.0, cell)
    dec = np.squeeze(FitsData(path).coords["DEC"].data)
    steps = np.diff(dec)
    # not exactly CDELT2: the projection is mildly non-linear away from the
    # reference pixel. The bug this guards against was a sign flip.
    np.testing.assert_allclose(steps, cell, rtol=1e-4)
    assert np.all(steps > 0), "DEC must increase with pixel index when CDELT2 > 0"


def test_grid_step_is_not_stretched(config):
    """Regression: np.linspace(a, a + scale*n, n) has step scale*n/(n-1), a 1.6% stretch at n=64."""
    cell, n = 20.0 / 3600, 64
    path, _ = write_image(config, n, n, 15.0, 0.0, cell)  # equator: RA step == |CDELT1|
    fds = FitsData(path)
    ra_steps = np.abs(np.diff(np.squeeze(fds.coords["RA"].data)))
    dec_steps = np.diff(np.squeeze(fds.coords["DEC"].data))
    stretch = n / (n - 1)
    np.testing.assert_allclose(ra_steps, cell, rtol=1e-4)
    np.testing.assert_allclose(dec_steps, cell, rtol=1e-4)
    assert ra_steps.mean() < cell * stretch * 0.999, "RA grid is stretched by n/(n-1)"


def test_longitude_step_carries_the_cos_dec_factor(config):
    """CDELT1 is an angle on the sky, so the RA step is CDELT1/cos(dec) at the reference row."""
    cell, dec0 = 20.0 / 3600, -60.0
    path, _ = write_image(config, 64, 64, 15.0, dec0, cell)
    ra = np.squeeze(FitsData(path).coords["RA"].data)
    step = np.abs(np.diff(ra)).mean()
    assert step == pytest.approx(cell / np.cos(np.deg2rad(dec0)), rel=1e-3)
    assert step > cell


def test_longitude_unwraps_across_zero(config):
    """A field straddling RA=0 must yield a monotonic longitude grid."""
    path, _ = write_image(config, 64, 64, 0.05, -31.0, 20.0 / 3600)
    ra = np.squeeze(FitsData(path).coords["RA"].data)
    steps = np.diff(ra)
    assert np.all(steps < 0), "RA must decrease monotonically (CDELT1 < 0), with no 360 deg jump"
    assert np.abs(steps).max() < 1.0


def test_pixel_size_attr_is_the_angular_cell(config):
    """pixel_size stays CDELT (the on-sky cell), which is not the RA coordinate step."""
    cell = 20.0 / 3600
    path, _ = write_image(config, 64, 64, 15.0, -31.0, cell)
    fds = FitsData(path)
    assert fds.coords["RA"].pixel_size == pytest.approx(-cell)
    assert fds.coords["DEC"].pixel_size == pytest.approx(cell)


def test_four_dimensional_cube(config):
    """Celestial grids must be right when STOKES and FREQ axes are present."""
    n = 64
    path, header = write_image(config, n, n, 15.0, -31.0, 20.0 / 3600, ndim=4)
    fds = FitsData(path)
    ra_expected, dec_expected = astropy_axis_grids(header, n, n)
    np.testing.assert_allclose(np.squeeze(fds.coords["RA"].data), ra_expected, atol=1e-12)
    np.testing.assert_allclose(np.squeeze(fds.coords["DEC"].data), dec_expected, atol=1e-12)


def test_a_planted_pixel_lands_where_the_wcs_says(config):
    """End-to-end: the coordinate of a chosen pixel must agree with astropy."""
    n, cell = 64, 20.0 / 3600
    path, header = write_image(config, n, n, 15.0, -31.0, cell, ndim=4)
    fds = FitsData(path)
    ra = np.squeeze(fds.coords["RA"].data)
    dec = np.squeeze(fds.coords["DEC"].data)

    ra_i, dec_i = 21, 39
    ra_true, dec_true = WCS(header).celestial.wcs_pix2world([[ra_i, dec_i]], 0)[0]
    # off the reference row/column the separable grid is only approximate, but it
    # must be well inside a pixel rather than the ~79 pixels it used to be out by
    assert abs(ra[ra_i] - ra_true) / cell < 0.1
    assert abs(dec[dec_i] - dec_true) / cell < 0.1
