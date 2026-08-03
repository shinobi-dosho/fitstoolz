"""Tests for FitsData: construction, coordinate registration, data access,
axis manipulation, beam handling and the xarray/FITS round trip.
"""

import pickle
from pathlib import Path

import dask
import numpy as np
import pytest
from astropy import units
from astropy.io import fits
from astropy.table import Table

from fitstoolz import reader
from fitstoolz.reader import FitsData

from . import InitTest

CELL = 20.0 / 3600
RA0, DEC0 = 15.0, -31.0
REST_FREQ = 1.42040575e9


@pytest.fixture
def config():
    return InitTest()


def make_header(npix, nchan=0, nstokes=0, spectral="FREQ", cunit3="Hz", cdelt3=1e6, crval3=1.4e9):
    header = fits.Header()
    header["CTYPE1"], header["CRVAL1"] = "RA---SIN", RA0
    header["CDELT1"], header["CRPIX1"], header["CUNIT1"] = -CELL, npix // 2 + 1, "deg"
    header["CTYPE2"], header["CRVAL2"] = "DEC--SIN", DEC0
    header["CDELT2"], header["CRPIX2"], header["CUNIT2"] = CELL, npix // 2 + 1, "deg"
    if nchan:
        header["CTYPE3"], header["CRVAL3"] = spectral, crval3
        header["CDELT3"], header["CRPIX3"], header["CUNIT3"] = cdelt3, 1, cunit3
        if spectral in ("VRAD", "VOPT"):
            header["RESTFRQ"] = REST_FREQ
    if nstokes:
        idx = 4 if nchan else 3
        header[f"CTYPE{idx}"], header[f"CRVAL{idx}"] = "STOKES", 1
        header[f"CDELT{idx}"], header[f"CRPIX{idx}"] = 1, 1
    return header


def write_fits(config, npix=32, nchan=0, nstokes=0, data=None, extra_hdus=(), **kwargs):
    header = make_header(npix, nchan, nstokes, **kwargs)
    shape = [npix, npix]
    if nchan:
        shape.insert(0, nchan)
    if nstokes:
        shape.insert(0, nstokes)
    if data is None:
        data = np.zeros(shape, dtype=np.float32)
    path = config.random_named_file(suffix=".fits")
    hdus = [fits.PrimaryHDU(data, header=header), *extra_hdus]
    fits.HDUList(hdus).writeto(path, overwrite=True)
    return path


# --------------------------------------------------------------------------- construction


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        FitsData("/nonexistent/image.fits")


@pytest.mark.filterwarnings("ignore::astropy.wcs.FITSFixedWarning")
def test_wcs_shape_mismatch_raises(config):
    """WCSAXES may declare more axes than the data has; that must be rejected.

    astropy drops the trailing axis from ``array_shape`` when NAXIS4 is absent,
    so this used to slip past the guard and fail later with an IndexError.
    """
    header = make_header(32, nchan=4)
    header["WCSAXES"] = 4
    header["CTYPE4"], header["CRVAL4"], header["CDELT4"], header["CRPIX4"] = "STOKES", 1, 1, 1
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((4, 32, 32), dtype=np.float32), header=header).writeto(path, overwrite=True)
    with pytest.raises(RuntimeError, match="does not match Image data"):
        FitsData(path)


def test_bunit_defaults_to_jy_and_is_stripped(config):
    path = write_fits(config)
    assert FitsData(path).data_units == "Jy"

    header = make_header(32)
    header["BUNIT"] = "  Jy/beam  "
    path2 = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((32, 32), np.float32), header=header).writeto(path2, overwrite=True)
    assert FitsData(path2).data_units == "Jy/beam"


# --------------------------------------------------------------------------- properties


def test_shape_and_dimension_properties(config):
    path = write_fits(config, npix=16, nchan=5, nstokes=2)
    fds = FitsData(path)
    assert fds.ndim == 4
    assert fds.dshape == (2, 5, 16, 16)
    assert fds.coord_names == ["STOKES", "FREQ", "DEC", "RA"]
    assert fds.dims == ["stokes", "spectral", "celestial.dec", "celestial.ra"]
    assert fds.coord_index("FREQ") == 1
    assert fds.nchan == 5


def test_nchan_is_zero_without_a_spectral_axis(config):
    fds = FitsData(write_fits(config))
    assert fds.spectral_coord is None
    assert fds.nchan == 0


def test_data_setter_round_trips(config):
    fds = FitsData(write_fits(config, npix=8))
    replacement = np.ones((8, 8), dtype=np.float32)
    fds.data = replacement
    np.testing.assert_array_equal(np.asarray(fds.data), replacement)


# --------------------------------------------------------------------------- coordinates


def test_spectral_grid_matches_the_wcs(config):
    nchan = 6
    path = write_fits(config, nchan=nchan)
    fds = FitsData(path)
    expected = 1.4e9 + np.arange(nchan) * 1e6
    np.testing.assert_allclose(np.squeeze(fds.coords["FREQ"].data), expected, rtol=1e-12)
    assert fds.spectral_coord == "FREQ"
    assert fds.spectral_refpix == 0
    assert fds.spectral_units == "Hz"


def test_stokes_grid_counts_from_crval(config):
    path = write_fits(config, nchan=2, nstokes=4)
    np.testing.assert_array_equal(np.squeeze(FitsData(path).coords["STOKES"].data), [1, 2, 3, 4])


@pytest.mark.parametrize("ctype", ["LINEAR", "PARAM"])
def test_unrecognised_axis_falls_back_to_pixel_indices(config, ctype):
    """Regression: an axis astropy cannot classify used to raise
    'TypeError: attribute name must be string, not NoneType'."""
    header = make_header(16)
    header["CTYPE3"], header["CRVAL3"], header["CDELT3"], header["CRPIX3"] = ctype, 0.0, 1.0, 1
    header["CUNIT3"] = ""
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((3, 16, 16), np.float32), header=header).writeto(path, overwrite=True)

    fds = FitsData(path)
    assert ctype in fds.coord_names
    assert fds.coords[ctype].size == 3
    np.testing.assert_array_equal(np.squeeze(fds.coords[ctype].data), np.arange(3))
    assert fds.dims == [ctype.lower(), "celestial.dec", "celestial.ra"]


@pytest.mark.parametrize("spectral", ["VRAD", "VOPT"])
def test_velocity_axes_convert_to_frequency(config, spectral):
    """The converted frequencies must bracket the rest frequency and be monotonic."""
    nchan = 5
    path = write_fits(config, nchan=nchan, spectral=spectral, cunit3="m/s", cdelt3=1e4, crval3=-2e4)
    fds = FitsData(path)
    assert fds.spectral_coord == spectral
    assert fds.spectral_restfreq == REST_FREQ

    freqs = fds.get_freq_from_vrad() if spectral == "VRAD" else fds.get_freq_from_vopt()
    assert freqs.shape == (nchan,)
    assert np.all(np.diff(freqs) < 0), "increasing velocity means decreasing frequency"

    # cross-check the zero-velocity channel against the rest frequency
    velocities = np.squeeze(fds.coords[spectral].data)
    zero = int(np.argmin(np.abs(velocities)))
    assert velocities[zero] == pytest.approx(0.0, abs=1e-9)
    assert freqs[zero] == pytest.approx(REST_FREQ, rel=1e-12)


def test_get_freq_from_vrad_accepts_an_explicit_rest_frequency(config):
    path = write_fits(config, nchan=3, spectral="VRAD", cunit3="m/s", cdelt3=1e4, crval3=0.0)
    fds = FitsData(path)
    assert fds.get_freq_from_vrad(rest_freq_Hz=1.0e9)[0] == pytest.approx(1.0e9, rel=1e-12)


# --------------------------------------------------------------------------- data access


def test_get_data_full_and_sliced(config):
    data = np.arange(4 * 8 * 8, dtype=np.float32).reshape(4, 8, 8)
    path = write_fits(config, npix=8, nchan=4, data=data)
    fds = FitsData(path)
    np.testing.assert_array_equal(fds.get_data(), data)
    # a slice is read lazily through phdu.section
    sliced = fds.get_data([slice(1, 3), slice(None), slice(None)])
    np.testing.assert_array_equal(sliced, data[1:3])
    assert len(fds.open_arrays) == 2


def test_get_xds_transposes_and_chunks(config):
    path = write_fits(config, npix=16, nchan=4, nstokes=2)
    fds = FitsData(path)
    xds = fds.get_xds(transpose=["STOKES", "RA", "DEC", "FREQ"], chunks={"RA": 8, "DEC": 8})
    assert xds.dims == ("stokes", "celestial.ra", "celestial.dec", "spectral")
    assert xds.shape == (2, 16, 16, 4)
    assert xds.chunks[1][0] == 8
    assert "header" in xds.attrs
    assert xds.attrs["header"]["CTYPE1"] == "RA---SIN"


def test_get_xds_defaults_to_native_order(config):
    fds = FitsData(write_fits(config, npix=16, nchan=3))
    xds = fds.get_xds()
    assert xds.dims == tuple(fds.dims)


def test_build_chunks(config):
    fds = FitsData(write_fits(config, npix=16, nchan=3))
    assert fds.build_chunks() == {}
    assert fds.build_chunks(ra_chunks=8, dec_chunks=4, spectral_chunks=2) == {"RA": 8, "DEC": 4, "FREQ": 2}

    no_spectral = FitsData(write_fits(config, npix=16))
    assert no_spectral.build_chunks(spectral_chunks=2) == {}, "no spectral axis, no spectral chunk"


# --------------------------------------------------------------------------- axis manipulation


def test_add_axis_prepends_a_stokes_axis(config):
    fds = FitsData(write_fits(config, npix=16, nchan=3))
    assert fds.ndim == 3
    fds.add_axis("STOKES", 4, crval=1, cdelt=1, crpix=0, cunit="")
    assert fds.ndim == 4
    assert fds.coord_names[0] == "STOKES"
    assert fds.dshape == (1, 3, 16, 16)


def test_add_axis_shifts_the_existing_header_keys(config):
    """Inserting at NAXIS1 must push RA/DEC/FREQ up by one."""
    fds = FitsData(write_fits(config, npix=16, nchan=3))
    fds.add_axis("PARAM", 1, crval=0, cdelt=1, crpix=0, cunit="")
    assert fds.ndim == 4
    assert fds.header["CTYPE1"] == "PARAM"
    assert fds.header["CTYPE2"] == "RA---SIN"
    assert fds.header["CTYPE3"] == "DEC--SIN"
    assert fds.header["CTYPE4"] == "FREQ"
    assert fds.dshape == (3, 16, 16, 1)
    assert fds.coord_names[-1] == "PARAM"


def test_expand_along_axis_grows_data_and_grid(config):
    fds = FitsData(write_fits(config, npix=8, nchan=2, nstokes=1))
    extra = np.ones((1, 2, 8, 8), dtype=np.float32)
    fds.expand_along_axis("STOKES", extra)
    assert fds.dshape == (2, 2, 8, 8)
    np.testing.assert_array_equal(np.squeeze(fds.coords["STOKES"].data), [1, 2])


def test_expand_along_axis_accepts_a_slice_with_one_fewer_dimension(config):
    """A plane of shape (nchan, n, n) is broadcast onto the stokes axis."""
    fds = FitsData(write_fits(config, npix=8, nchan=2, nstokes=1))
    fds.expand_along_axis("STOKES", np.ones((2, 8, 8), dtype=np.float32))
    assert fds.dshape == (2, 2, 8, 8)
    assert np.all(np.asarray(fds.data)[1] == 1.0)


def test_expand_along_axis_appends_beam_rows(config):
    beam_hdu = fits.BinTableHDU(Table({"BMAJ": [0.2, 0.2], "BMIN": [0.1, 0.1], "BPA": [30.0, 30.0]}))
    fds = FitsData(write_fits(config, npix=8, nchan=2, nstokes=1, extra_hdus=(beam_hdu,)))
    assert len(fds.beam_table) == 2
    extra_beams = Table({"BMAJ": [0.3, 0.3], "BMIN": [0.15, 0.15], "BPA": [45.0, 45.0]})
    fds.expand_along_axis("STOKES", np.ones((1, 2, 8, 8), dtype=np.float32), beams=extra_beams)
    assert len(fds.beam_table) == 4
    assert fds.beam_table["BMAJ"][-1] == pytest.approx(0.3)


def test_expand_along_axis_from_files_stacks_stokes(config):
    """The pattern simms uses to combine per-Stokes FITS images."""
    base = write_fits(config, npix=8, nchan=2, nstokes=1, data=np.zeros((1, 2, 8, 8), np.float32))
    others = [
        write_fits(config, npix=8, nchan=2, nstokes=1, data=np.full((1, 2, 8, 8), fill, np.float32))
        for fill in (1.0, 2.0, 3.0)
    ]
    fds = FitsData(base)
    fds.expand_along_axis_from_files("STOKES", others)
    assert fds.dshape == (4, 2, 8, 8)
    cube = np.asarray(fds.data)
    for plane, fill in enumerate([0.0, 1.0, 2.0, 3.0]):
        assert np.all(cube[plane] == fill)


# --------------------------------------------------------------------------- beams


def test_no_beam_information_yields_none(config):
    assert FitsData(write_fits(config)).beam_table is None


def test_beam_from_header(config):
    header = make_header(16, nchan=2)
    header["BMAJ"], header["BMIN"], header["BPA"] = 0.2, 0.1, 45.0
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((2, 16, 16), np.float32), header=header).writeto(path, overwrite=True)
    beams = FitsData(path).beam_table
    assert beams is not None
    assert beams["BMAJ"][0] > 0


def test_single_beam_is_scaled_as_one_over_frequency_across_a_cube(config):
    """A one-row beam table on a multi-channel cube is expanded, scaling as ref_freq/freq."""
    nchan = 4
    beam_hdu = fits.BinTableHDU(Table({"BMAJ": [0.2], "BMIN": [0.1], "BPA": [30.0]}))
    path = write_fits(config, npix=16, nchan=nchan, extra_hdus=(beam_hdu,))
    fds = FitsData(path)
    beams = fds.beam_table
    assert len(beams) == nchan

    freqs = np.squeeze(fds.coords["FREQ"].data)
    expected = 0.2 * freqs[fds.spectral_refpix] / freqs
    np.testing.assert_allclose(np.asarray(beams["BMAJ"]), expected, rtol=1e-9)
    np.testing.assert_allclose(np.asarray(beams["BMIN"]), 0.1 * freqs[0] / freqs, rtol=1e-9)
    np.testing.assert_allclose(np.asarray(beams["BPA"]), 30.0)


def test_per_channel_beam_table_is_left_alone(config):
    nchan = 3
    beam_hdu = fits.BinTableHDU(Table({"BMAJ": [0.2, 0.3, 0.4], "BMIN": [0.1] * 3, "BPA": [30.0] * 3}))
    path = write_fits(config, npix=16, nchan=nchan, extra_hdus=(beam_hdu,))
    beams = FitsData(path).beam_table
    np.testing.assert_allclose(np.asarray(beams["BMAJ"]), [0.2, 0.3, 0.4])


# --------------------------------------------------------------------------- round trip / lifecycle


def test_write_to_fits_round_trip(config):
    data = np.random.default_rng(0).normal(size=(3, 16, 16)).astype(np.float32)
    path = write_fits(config, npix=16, nchan=3, data=data)
    fds = FitsData(path)
    # random_named_file creates the file, so this also exercises overwrite=True.
    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, coord_names=["FREQ", "DEC", "RA"], overwrite=True)

    reread = FitsData(out)
    assert reread.dshape == (3, 16, 16)
    np.testing.assert_allclose(np.asarray(reread.data), data, rtol=1e-6)
    np.testing.assert_allclose(np.squeeze(reread.coords["FREQ"].data), np.squeeze(fds.coords["FREQ"].data), rtol=1e-12)


def test_write_to_fits_refuses_to_clobber_by_default(config):
    fds = FitsData(write_fits(config, npix=8, nchan=2))
    out = config.random_named_file(suffix=".fits")
    with pytest.raises(FileExistsError, match="already exists"):
        fds.write_to_fits(out)


def test_write_to_fits_leaves_no_temporary_behind(config):
    """The write goes via a sibling temp file; it must not survive the call."""
    fds = FitsData(write_fits(config, npix=8, nchan=2))
    out = Path(config.random_named_file(suffix=".fits"))
    fds.write_to_fits(out, overwrite=True)
    assert not list(out.parent.glob(".*fitstoolz-tmp"))


def test_failed_write_leaves_the_original_intact(config, monkeypatch):
    """The staged write is what makes replacing a file atomic."""
    data = np.random.default_rng(4).normal(size=(2, 8, 8)).astype(np.float32)
    path = Path(write_fits(config, npix=8, nchan=2, data=data))
    fds = FitsData(write_fits(config, npix=8, nchan=2))

    def explode(self, name, *args, **kwargs):
        # Half-write the temporary before failing, the way a full disk would, so
        # the cleanup path is what gets exercised rather than a no-op.
        Path(name).write_bytes(b"SIMPLE  =                    T" + b" " * 50)
        raise OSError("disk full")

    monkeypatch.setattr(fits.HDUList, "writeto", explode)
    with pytest.raises(OSError, match="disk full"):
        fds.write_to_fits(path, overwrite=True)

    np.testing.assert_allclose(fits.getdata(path), data, rtol=1e-6)
    assert not list(path.parent.glob(".*fitstoolz-tmp"))


@pytest.mark.filterwarnings("ignore::astropy.wcs.FITSFixedWarning")
def test_header_only_hdu_is_reported_not_read(config):
    """A primary HDU with no data has nothing to chunk; say so clearly."""
    path = config.random_named_file(suffix=".fits")
    fits.HDUList([fits.PrimaryHDU()]).writeto(path, overwrite=True)
    with pytest.raises(RuntimeError, match="does not match Image data"):
        FitsData(path)


def test_write_in_place_does_not_corrupt_the_source(config):
    """`--replace` writes over the file the lazy blocks are still reading from.

    With the data read on demand rather than up front, writing straight to the
    destination truncates the source mid-read. The write goes through a
    temporary and is renamed into place precisely so this stays correct.
    """
    data = np.random.default_rng(3).normal(size=(4, 16, 16)).astype(np.float32)
    path = write_fits(config, npix=16, nchan=4, data=data)

    with FitsData(path) as fds:
        fds.write_to_fits(path, overwrite=True)

    np.testing.assert_allclose(np.asarray(FitsData(path).data), data, rtol=1e-6)


# --------------------------------------------------------------------------- beam tables on write


def beam_hdu(nrows, name="BEAMS", **meta):
    table = Table(
        {
            "BMAJ": np.linspace(0.4, 0.2, nrows),
            "BMIN": np.linspace(0.2, 0.1, nrows),
            "BPA": np.full(nrows, 30.0),
            "CHAN": np.arange(nrows),
            "POL": np.zeros(nrows, dtype=int),
        }
    )
    for col in ("BMAJ", "BMIN", "BPA"):
        table[col].unit = units.deg
    hdu = fits.BinTableHDU(table, name=name)
    for key, value in meta.items():
        hdu.header[key] = value
    return hdu


def test_beam_extension_survives_a_write(config):
    """A per-channel beam table used to be dropped: only a PrimaryHDU was written."""
    path = write_fits(config, npix=8, nchan=4, extra_hdus=(beam_hdu(4),))
    out = config.random_named_file(suffix=".fits")
    FitsData(path).write_to_fits(out, overwrite=True)

    with fits.open(out) as hdulist:
        assert [hdu.name for hdu in hdulist] == ["PRIMARY", "BEAMS"]
    reread = FitsData(out)
    np.testing.assert_allclose(np.asarray(reread.beam_table["BMAJ"]), np.linspace(0.4, 0.2, 4))
    assert str(reread.beam_table["BMAJ"].unit) == "deg"


def test_beam_extension_name_and_metadata_are_preserved(config):
    path = write_fits(config, npix=8, nchan=3, extra_hdus=(beam_hdu(3, name="CASAMBM", NCHAN=3),))
    out = config.random_named_file(suffix=".fits")
    FitsData(path).write_to_fits(out, overwrite=True)

    with fits.open(out) as hdulist:
        assert hdulist[1].name == "CASAMBM"
        assert hdulist[1].header["NCHAN"] == 3


def test_beam_rows_follow_a_spectral_slice(config):
    path = write_fits(config, npix=8, nchan=8, extra_hdus=(beam_hdu(8, NCHAN=8),))
    fds = FitsData(path)
    out = config.random_named_file(suffix=".fits")
    data_slice = [slice(2, 5), slice(None), slice(None)]
    fds.write_to_fits(out, data_slice=data_slice, overwrite=True)

    reread = FitsData(out)
    assert reread.dshape == (3, 8, 8)
    np.testing.assert_allclose(np.asarray(reread.beam_table["BMAJ"]), np.linspace(0.4, 0.2, 8)[2:5])
    # CHAN describes the written channels, not the ones they came from.
    np.testing.assert_array_equal(np.asarray(reread.beam_table["CHAN"]), [0, 1, 2])
    with fits.open(out) as hdulist:
        assert hdulist[1].header["NCHAN"] == 3


def test_header_keyword_beams_do_not_become_an_extension(config):
    """BMAJ/BMIN/BPA ride along in the header; a table would invent an extension.

    A single beam is expanded per channel in memory, and that expansion is this
    package's model rather than something the file recorded -- writing it out as
    a table would promote the model to data.
    """
    header = make_header(8, nchan=4)
    header["BMAJ"], header["BMIN"], header["BPA"] = 1e-3, 1e-3, 0.0
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((4, 8, 8), np.float32), header=header).writeto(path, overwrite=True)

    fds = FitsData(path)
    assert len(fds.beam_table) == 4, "single beam should still be expanded in memory"

    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, overwrite=True)
    with fits.open(out) as hdulist:
        assert [hdu.name for hdu in hdulist] == ["PRIMARY"]
        assert hdulist[0].header["BMAJ"] == 1e-3


def test_stacked_beams_reach_the_output(config):
    """`stack` accumulates rows through expand_along_axis; they must be written."""
    first = write_fits(config, npix=8, nchan=2, extra_hdus=(beam_hdu(2),))
    second = write_fits(config, npix=8, nchan=2, extra_hdus=(beam_hdu(2),))

    fds = FitsData(first)
    fds.expand_along_axis_from_files("FREQ", [second])
    assert len(fds.beam_table) == 4

    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, overwrite=True)
    assert len(FitsData(out).beam_table) == 4


# --------------------------------------------------------------------------- regrid_axis


def test_regrid_axis_changes_the_channel_count(config):
    """The gap this closes: coords is an xr.Coordinates and will not be realigned."""
    path = write_fits(config, npix=8, nchan=32)
    fds = FitsData(path)

    with pytest.raises(Exception, match="conflicting dimension sizes|cannot reindex|align"):
        fds.coords["FREQ"] = ("spectral",), np.arange(29, dtype=float)

    new_grid = 1.4001e9 + np.arange(29) * 1.0001e6
    fds.regrid_axis("FREQ", new_grid, np.ones((29, 8, 8), dtype=np.float32))

    assert fds.dshape == (29, 8, 8)
    assert fds.nchan == 29
    np.testing.assert_allclose(np.squeeze(fds.coords["FREQ"].data), new_grid, rtol=1e-12)


def test_regrid_axis_round_trips_through_a_file(config):
    path = write_fits(config, npix=8, nchan=32)
    fds = FitsData(path)
    new_grid = 1.4001e9 + np.arange(29) * 1.0001e6
    data = np.random.default_rng(5).normal(size=(29, 8, 8)).astype(np.float32)
    fds.regrid_axis("FREQ", new_grid, data)

    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, overwrite=True)

    header = fits.getheader(out)
    assert header["NAXIS3"] == 29
    assert header["CRPIX3"] == 1
    np.testing.assert_allclose(header["CRVAL3"], new_grid[0], rtol=1e-12)
    np.testing.assert_allclose(header["CDELT3"], 1.0001e6, rtol=1e-9)

    reread = FitsData(out)
    np.testing.assert_allclose(np.asarray(reread.data), data, rtol=1e-6)
    np.testing.assert_allclose(np.squeeze(reread.coords["FREQ"].data), new_grid, rtol=1e-9)


def test_regrid_axis_rejects_a_non_linear_grid(config):
    """A FITS axis is CRVAL/CDELT; an uneven grid cannot be written as one."""
    fds = FitsData(write_fits(config, npix=8, nchan=4))
    uneven = np.array([1.4e9, 1.401e9, 1.403e9, 1.409e9])
    with pytest.raises(ValueError, match="evenly spaced"):
        fds.regrid_axis("FREQ", uneven, np.ones((4, 8, 8), dtype=np.float32))


def test_regrid_axis_rejects_mismatched_data(config):
    fds = FitsData(write_fits(config, npix=8, nchan=4))
    grid = 1.4e9 + np.arange(6) * 1e6
    with pytest.raises(ValueError, match="6 coordinates were given|elements along"):
        fds.regrid_axis("FREQ", grid, np.ones((5, 8, 8), dtype=np.float32))
    with pytest.raises(ValueError, match="only changes 'FREQ'"):
        fds.regrid_axis("FREQ", grid, np.ones((6, 16, 8), dtype=np.float32))


def test_regrid_axis_rejects_data_of_the_wrong_rank(config):
    fds = FitsData(write_fits(config, npix=8, nchan=4))
    with pytest.raises(ValueError, match="axes, but this cube has 3"):
        fds.regrid_axis("FREQ", 1.4e9 + np.arange(4) * 1e6, np.ones((4, 8), dtype=np.float32))


def test_regrid_axis_to_a_single_channel_keeps_the_old_width(config):
    """One value defines no spacing, so CDELT has to come from the header."""
    fds = FitsData(write_fits(config, npix=8, nchan=4, cdelt3=2e6))
    fds.regrid_axis("FREQ", np.array([1.41e9]), np.ones((1, 8, 8), dtype=np.float32))
    assert fds.nchan == 1
    assert fds.header["CDELT3"] == 2e6
    np.testing.assert_allclose(np.squeeze(fds.coords["FREQ"].data), [1.41e9], rtol=1e-12)


def test_regrid_axis_handles_a_descending_axis(config):
    """A negative CDELT runs the grid backwards; interpolation must cope."""
    path = write_fits(config, npix=8, nchan=8, extra_hdus=(beam_hdu(8),), cdelt3=-1e6)
    fds = FitsData(path)
    old = np.squeeze(np.asarray(fds.coords["FREQ"].data))
    new_grid = np.linspace(old[0], old[-1], 5)
    fds.regrid_axis("FREQ", new_grid, np.ones((5, 8, 8), dtype=np.float32))

    assert len(fds.beam_table) == 5
    expected = np.interp(new_grid[::-1], old[::-1], np.linspace(0.4, 0.2, 8)[::-1])[::-1]
    np.testing.assert_allclose(np.asarray(fds.beam_table["BMAJ"]), expected, rtol=1e-9)


def test_regrid_axis_interpolates_the_beam_table(config):
    path = write_fits(config, npix=8, nchan=8, extra_hdus=(beam_hdu(8, NCHAN=8),))
    fds = FitsData(path)
    old = np.squeeze(np.asarray(fds.coords["FREQ"].data))
    new_grid = np.linspace(old[0], old[-1], 4)
    fds.regrid_axis("FREQ", new_grid, np.ones((4, 8, 8), dtype=np.float32))

    expected = np.interp(new_grid, old, np.linspace(0.4, 0.2, 8))
    np.testing.assert_allclose(np.asarray(fds.beam_table["BMAJ"]), expected, rtol=1e-9)
    np.testing.assert_array_equal(np.asarray(fds.beam_table["CHAN"]), [0, 1, 2, 3])
    assert str(fds.beam_table["BMAJ"].unit) == "deg"

    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, overwrite=True)
    with fits.open(out) as hdulist:
        assert hdulist[1].header["NCHAN"] == 4
    np.testing.assert_allclose(np.asarray(FitsData(out).beam_table["BMAJ"]), expected, rtol=1e-6)


def test_regrid_axis_onto_a_grid_in_different_units(config):
    """`values` are header units; `coords` come back in the units astropy reports.

    astropy normalises a spectral coordinate to SI whatever CUNIT says, so a
    beam interpolation that compared `values` against the coords grid would be
    out by a factor of a million on this cube.
    """
    path = write_fits(config, npix=8, nchan=8, extra_hdus=(beam_hdu(8),))
    fds = FitsData(path)
    old_hz = np.squeeze(np.asarray(fds.coords["FREQ"].data))

    new_mhz = np.linspace(old_hz[0], old_hz[-1], 4) / 1e6
    fds.regrid_axis("FREQ", new_mhz, np.ones((4, 8, 8), dtype=np.float32), cunit="MHz")

    assert fds.header["CUNIT3"] == "MHz"
    np.testing.assert_allclose(fds.header["CRVAL3"], new_mhz[0], rtol=1e-12)
    # Still SI on the way back out, so it agrees with the pre-regrid grid.
    np.testing.assert_allclose(np.squeeze(fds.coords["FREQ"].data), new_mhz * 1e6, rtol=1e-9)

    expected = np.interp(new_mhz * 1e6, old_hz, np.linspace(0.4, 0.2, 8))
    np.testing.assert_allclose(np.asarray(fds.beam_table["BMAJ"]), expected, rtol=1e-9)


def test_regrid_axis_leaves_a_whole_cube_beam_alone(config):
    """A single-row table describes the cube, not its channels."""
    path = write_fits(config, npix=8, nchan=1, extra_hdus=(beam_hdu(1),))
    fds = FitsData(path)
    assert len(fds.beam_table) == 1
    fds.regrid_axis("FREQ", np.array([1.4e9, 1.401e9, 1.402e9]), np.ones((3, 8, 8), dtype=np.float32))
    assert len(fds.beam_table) == 1


# --------------------------------------------------------------------------- laziness


def test_data_is_not_read_at_construction(config):
    """Opening a file must cost a header parse, not a cube.

    The graph is the measurable proxy: a materialised array is embedded in it, so
    its serialised size tracks the data. A graph of on-demand reads carries only
    slices and a filename, and stays flat as the cube grows.
    """
    small = FitsData(write_fits(config, npix=16, nchan=2))  # 2 KiB
    large = FitsData(write_fits(config, npix=64, nchan=64))  # 1 MiB

    small_graph = len(pickle.dumps(dict(small.data.dask)))
    large_graph = len(pickle.dumps(dict(large.data.dask)))

    assert large.data.nbytes > 100 * small.data.nbytes
    assert large_graph < 8192, f"graph is {large_graph} bytes -- the data looks embedded in it"
    assert large_graph < 2 * small_graph


def test_blocks_read_only_their_own_slice(config, monkeypatch):
    """Computing one block must not pull in the neighbouring ones."""
    data = np.random.default_rng(1).normal(size=(8, 16, 16)).astype(np.float32)
    path = write_fits(config, npix=16, nchan=8, data=data)

    reads = []
    original = reader.read_block

    # block_info has to be named: map_blocks introspects for that keyword and
    # only passes it to a function that declares it.
    def spy(*args, block_info=None, **kwargs):
        result = original(*args, block_info=block_info, **kwargs)
        reads.append(result.size)
        return result

    # Patch before construction: map_blocks captures the function at graph-build
    # time. One channel plane is 1 KiB, so this chunks to a block per channel.
    monkeypatch.setattr(reader, "read_block", spy)
    with dask.config.set({"array.chunk-size": "1kiB"}):
        fds = FitsData(path)
        assert fds.data.numblocks[0] == 8
        block = fds.data.blocks[2, 0, 0].compute()

    np.testing.assert_allclose(block[0], data[2], rtol=1e-6)
    assert sum(reads) < data.size


def test_lazy_read_matches_the_file_including_scaled_data(config):
    """Round-trip equality, and the BSCALE/BZERO path that fixes the block dtype."""
    raw = np.arange(3 * 8 * 8, dtype=np.int16).reshape(3, 8, 8)
    header = make_header(8, nchan=3)
    header["BZERO"], header["BSCALE"] = 100.0, 0.5
    path = config.random_named_file(suffix=".fits")
    hdu = fits.PrimaryHDU(raw, header=header)
    hdu.writeto(path, overwrite=True)

    expected = fits.getdata(path)
    fds = FitsData(path)
    assert fds.data.dtype == expected.dtype
    np.testing.assert_allclose(np.asarray(fds.data), expected, rtol=1e-6)


def test_graph_survives_closing_the_file(config):
    """A graph carrying its own filename can be computed after the handle closes."""
    data = np.random.default_rng(2).normal(size=(2, 8, 8)).astype(np.float32)
    path = write_fits(config, npix=8, nchan=2, data=data)
    with FitsData(path) as fds:
        lazy = fds.data
    np.testing.assert_allclose(np.asarray(lazy), data, rtol=1e-6)


def test_context_manager_closes_the_file(config):
    path = write_fits(config)
    with FitsData(path) as fds:
        assert fds.hdulist is not None
    assert fds.hdulist.fileinfo(0) is None or fds.hdulist[0]._file.closed


def test_close_is_idempotent_with_open_arrays(config):
    fds = FitsData(write_fits(config, npix=8, nchan=2))
    fds.get_data()
    fds.close()
    assert fds.open_arrays


@pytest.mark.parametrize("spectral", ["VRAD", "VOPT"])
def test_single_beam_scaling_uses_velocity_derived_frequencies(config, spectral):
    """A one-row beam on a velocity cube must scale against the converted frequencies."""
    nchan = 4
    beam_hdu = fits.BinTableHDU(Table({"BMAJ": [0.2], "BMIN": [0.1], "BPA": [30.0]}))
    path = write_fits(
        config,
        npix=16,
        nchan=nchan,
        extra_hdus=(beam_hdu,),
        spectral=spectral,
        cunit3="m/s",
        cdelt3=1e4,
        crval3=-2e4,
    )
    fds = FitsData(path)
    freqs = fds.get_freq_from_vrad() if spectral == "VRAD" else fds.get_freq_from_vopt()
    expected = 0.2 * freqs[fds.spectral_refpix] / freqs
    np.testing.assert_allclose(np.asarray(fds.beam_table["BMAJ"]), expected, rtol=1e-9)


def test_set_celestial_dimensions_without_celestial_axes(config):
    """Calling it on a cube that has no sky axes must fail loudly."""
    header = fits.Header()
    header["CTYPE1"], header["CRVAL1"], header["CDELT1"], header["CRPIX1"], header["CUNIT1"] = (
        "FREQ",
        1.4e9,
        1e6,
        1,
        "Hz",
    )
    header["CTYPE2"], header["CRVAL2"], header["CDELT2"], header["CRPIX2"] = "STOKES", 1, 1, 1
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((2, 4), np.float32), header=header).writeto(path, overwrite=True)
    fds = FitsData(path)
    with pytest.raises(RuntimeError, match="does not define a pair of celestial axes"):
        fds.set_celestial_dimensions()


def test_beam_units_survive_expansion(config):
    """Units on the beam columns must be preserved when a single beam is broadcast."""
    beams_in = Table({"BMAJ": [0.2] * 1, "BMIN": [0.1] * 1, "BPA": [30.0] * 1})
    for col in beams_in.colnames:
        beams_in[col].unit = units.deg
    path = write_fits(config, npix=16, nchan=3, extra_hdus=(fits.BinTableHDU(beams_in),))
    beams = FitsData(path).beam_table
    assert beams["BMAJ"].unit == units.deg
