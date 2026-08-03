import numpy as np
import pytest
from astropy import units
from astropy.io import fits
from astropy.wcs import WCS

from fitstoolz.utils import beam_unit, contiguous_chunks, get_beam_table, reorder_wcs

from . import InitTest


@pytest.fixture
def config():
    return InitTest()


# --------------------------------------------------------------------------- contiguous_chunks


def test_contiguous_chunks_keeps_a_small_array_whole():
    assert contiguous_chunks((4, 32, 32), "f4", limit="1MiB") == (4, 32, 32)


def test_contiguous_chunks_splits_the_slowest_axis_that_does_not_fit():
    # One 32x32 float32 plane is 4 KiB, so a 16 KiB limit holds four of them.
    assert contiguous_chunks((100, 32, 32), "f4", limit=16 * 1024) == (4, 32, 32)


def test_contiguous_chunks_keeps_trailing_axes_whole():
    """Splitting a trailing axis would scatter the read across the file."""
    chunks = contiguous_chunks((2, 512, 450, 450), "f4", limit="8MiB")
    assert chunks[-2:] == (450, 450)
    assert chunks[0] == 1, "axes slower than the split one go to a single element"
    assert 0 < chunks[1] < 512


def test_contiguous_chunks_steps_over_a_degenerate_leading_axis():
    """A length-1 Stokes axis cannot bound the chunk; the split must move inwards."""
    chunks = contiguous_chunks((1, 512, 450, 450), "f4", limit="8MiB")
    assert chunks[0] == 1
    assert chunks[1] < 512
    assert np.prod(chunks) * 4 <= 8 * 1024**2


def test_contiguous_chunks_never_returns_a_zero_length_chunk():
    """A limit smaller than one row still has to yield a readable block."""
    assert contiguous_chunks((8, 64, 64), "f8", limit=1) == (1, 1, 1)


def test_reorder_wcs():
    wcs = WCS(naxis=3)
    wcs.wcs.ctype = ["RA---SIN", "DEC--SIN", "FREQ"]
    wcs.wcs.crval = [2.0, -30.0, 1.4e9]
    wcs.wcs.crpix = [64.0, 64.0, 1.0]
    wcs.wcs.cdelt = [-0.001, 0.001, 1e6]
    wcs.wcs.cunit = ["deg", "deg", "Hz"]

    old_order = ["RA---SIN", "DEC--SIN", "FREQ"]
    new_order = ["FREQ", "DEC--SIN", "RA---SIN"]

    result = reorder_wcs(wcs, old_order, new_order)

    assert result.naxis == 3
    assert list(result.wcs.ctype) == new_order
    assert list(result.wcs.crval) == [1.4e9, -30.0, 2.0]
    assert list(result.wcs.cdelt) == [1e6, 0.001, -0.001]
    assert list(result.wcs.cunit) == ["Hz", "deg", "deg"]


def test_get_beam_table_bintable(config: InitTest):
    pix_size = 5 / 3600
    npix = 64
    wcs = WCS(naxis=3)
    wcs.wcs.ctype = ["RA---SIN", "DEC--SIN", "FREQ"]
    wcs.wcs.cdelt = np.array([-pix_size, pix_size, 1e6])
    wcs.wcs.crpix = [npix / 2, npix / 2, 1]
    wcs.wcs.crval = [2.0, -30, 1.4e9]
    wcs.wcs.cunit = ["deg", "deg", "Hz"]
    header = wcs.to_header()

    image = np.zeros((1, npix, npix), dtype=np.float32)
    phdu = fits.PrimaryHDU(image, header=header)

    from astropy.table import Table

    beam_tab = Table(
        {
            "BMAJ": [0.1],
            "BMIN": [0.05],
            "BPA": [30.0],
        }
    )
    beam_hdu = fits.BinTableHDU(beam_tab)
    hdul = fits.HDUList([phdu, beam_hdu])

    fname = config.random_named_file(suffix=".fits")
    hdul.writeto(fname, overwrite=True)

    result = get_beam_table(fname)
    assert result is not False
    assert result["BMAJ"][0] == 0.1
    assert result["BMIN"][0] == 0.05
    assert result["BPA"][0] == 30.0


def test_get_beam_table_header(config: InitTest):
    pix_size = 5 / 3600
    npix = 64
    wcs = WCS(naxis=3)
    wcs.wcs.ctype = ["RA---SIN", "DEC--SIN", "FREQ"]
    wcs.wcs.cdelt = np.array([-pix_size, pix_size, 1e6])
    wcs.wcs.crpix = [npix / 2, npix / 2, 1]
    wcs.wcs.crval = [2.0, -30, 1.4e9]
    wcs.wcs.cunit = ["deg", "deg", "Hz"]
    header = wcs.to_header()
    header["BMAJ"] = 0.2
    header["BMIN"] = 0.1
    header["BPA"] = 45.0

    image = np.zeros((1, npix, npix), dtype=np.float32)
    hdu = fits.PrimaryHDU(image, header=header)
    hdul = fits.HDUList([hdu])

    fname = config.random_named_file(suffix=".fits")
    hdul.writeto(fname, overwrite=True)

    result = get_beam_table(fname)
    assert result is not False
    assert result["BMAJ"][0] > 0
    assert result["BPA"][0] > 0


def test_get_beam_table_missing_file():
    with pytest.raises(FileNotFoundError):
        get_beam_table("/nonexistent/file.fits")


def _celestial_header(cunit1="deg"):
    pix_size = 5 / 3600
    wcs = WCS(naxis=3)
    wcs.wcs.ctype = ["RA---SIN", "DEC--SIN", "FREQ"]
    wcs.wcs.cdelt = np.array([-pix_size, pix_size, 1e6])
    wcs.wcs.crpix = [32, 32, 1]
    wcs.wcs.crval = [2.0, -30, 1.4e9]
    wcs.wcs.cunit = [cunit1, "deg", "Hz"]
    return wcs.to_header()


def test_beam_unit_defaults_to_deg_for_a_non_angle_first_axis():
    """Regression: getattr(units, 'hz') raised AttributeError for a FREQ-leading cube."""
    header = fits.Header()
    header["CUNIT1"] = "Hz"
    assert beam_unit(header) == units.deg

    header["CUNIT1"] = "not-a-unit"
    assert beam_unit(header) == units.deg

    del header["CUNIT1"]
    assert beam_unit(header) == units.deg


def test_beam_unit_honours_an_angular_first_axis():
    header = fits.Header()
    header["CUNIT1"] = "arcsec"
    assert beam_unit(header) == units.arcsec


def test_get_beam_table_without_any_beam_returns_false(config: InitTest):
    """A cube leading with a spectral axis and carrying no beam must not raise."""
    header = fits.Header()
    header["CTYPE1"], header["CRVAL1"], header["CDELT1"], header["CRPIX1"], header["CUNIT1"] = (
        "FREQ",
        1.4e9,
        1e6,
        1,
        "Hz",
    )
    header["CTYPE2"], header["CRVAL2"], header["CDELT2"], header["CRPIX2"] = "STOKES", 1, 1, 1
    fname = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((2, 4), np.float32), header=header).writeto(fname, overwrite=True)
    assert get_beam_table(fname) is False


def test_get_beam_table_per_channel_header_keywords(config: InitTest):
    """BMAJ1/BMIN1/BPA1, BMAJ2/... describe a beam per channel."""
    header = _celestial_header()
    for chan, (bmaj, bmin, bpa) in enumerate([(0.3, 0.15, 10.0), (0.2, 0.1, 20.0), (0.1, 0.05, 30.0)], start=1):
        header[f"BMAJ{chan}"], header[f"BMIN{chan}"], header[f"BPA{chan}"] = bmaj, bmin, bpa

    fname = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((3, 64, 64), np.float32), header=header).writeto(fname, overwrite=True)

    result = get_beam_table(fname)
    assert result is not False
    assert len(result) == 3
    np.testing.assert_allclose(np.asarray(result["BMAJ"]), [0.3, 0.2, 0.1])
    assert result["BMAJ"].unit == units.deg
    np.testing.assert_array_equal(result["CHAN"], [0, 1, 2])
    np.testing.assert_array_equal(result["POL"], [0, 0, 0])


def test_bintable_beam_takes_precedence_over_header_keywords(config: InitTest):
    from astropy.table import Table

    header = _celestial_header()
    header["BMAJ"], header["BMIN"], header["BPA"] = 0.9, 0.9, 0.0
    beam_hdu = fits.BinTableHDU(Table({"BMAJ": [0.1], "BMIN": [0.05], "BPA": [30.0]}))
    fname = config.random_named_file(suffix=".fits")
    fits.HDUList([fits.PrimaryHDU(np.zeros((1, 64, 64), np.float32), header=header), beam_hdu]).writeto(
        fname, overwrite=True
    )
    result = get_beam_table(fname)
    assert result["BMAJ"][0] == 0.1
