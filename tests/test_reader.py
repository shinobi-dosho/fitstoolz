"""Tests for FitsData: construction, coordinate registration, data access,
axis manipulation, beam handling and the xarray/FITS round trip.
"""

import logging
import os
import pickle
from pathlib import Path

import dask
import numpy as np
import pytest
from astropy import units
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

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


def staged_files(destination):
    """The temporaries `write_to_fits` stages this destination through.

    Matched against the destination rather than the whole directory: every test
    here writes into the same directory, so a broader glob picks up other tests'
    files.
    """
    destination = Path(destination)
    return list(destination.parent.glob(f".{destination.name}.*.fitstoolz-tmp"))


def test_write_to_fits_leaves_no_temporary_behind(config):
    """The write goes via a sibling temp file; it must not survive the call."""
    fds = FitsData(write_fits(config, npix=8, nchan=2))
    out = Path(config.random_named_file(suffix=".fits"))
    fds.write_to_fits(out, overwrite=True)
    assert not staged_files(out)


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
    assert not staged_files(path)


def test_the_temporary_is_named_per_process(config):
    """The rest of the name comes from the destination, so two writers would collide."""
    staged = []
    fds = FitsData(write_fits(config, npix=8, nchan=2))
    out = Path(config.random_named_file(suffix=".fits"))

    real_writeto = fits.HDUList.writeto

    def spy(self, name, *args, **kwargs):
        staged.append(Path(name).name)
        return real_writeto(self, name, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fits.HDUList, "writeto", spy)
        fds.write_to_fits(out, overwrite=True)

    assert staged == [f".{out.name}.{os.getpid()}.fitstoolz-tmp"]


def test_a_rename_that_fails_keeps_the_finished_output(config, monkeypatch):
    """Losing the rename is no reason to throw away a write that succeeded."""
    existing = np.random.default_rng(11).normal(size=(2, 8, 8)).astype(np.float32)
    out = Path(write_fits(config, npix=8, nchan=2, data=existing))
    fds = FitsData(write_fits(config, npix=8, nchan=2, data=np.ones((2, 8, 8), np.float32)))

    def refuse(src, dst):
        raise OSError("cross-device link")

    monkeypatch.setattr(reader.os, "replace", refuse)
    with pytest.raises(OSError, match="intact at"):
        fds.write_to_fits(out, overwrite=True)

    np.testing.assert_allclose(fits.getdata(out), existing, rtol=1e-6, err_msg="the destination is untouched")

    staged = staged_files(out)
    try:
        assert len(staged) == 1, "the finished output should still be there"
        np.testing.assert_allclose(fits.getdata(staged[0]), 1.0)
    finally:
        for leftover in staged:
            leftover.unlink()


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


def test_beam_rows_follow_a_dropped_spectral_axis(config):
    """`remove-axis --ctype FREQ` selects one channel; the table must follow it.

    The cut used to be skipped whenever the spectral axis was absent from
    ``coord_names`` -- which is exactly what dropping it does -- so a whole
    per-channel table was written beside a single plane, as though all of those
    beams described it.
    """
    path = write_fits(config, npix=8, nchan=8, extra_hdus=(beam_hdu(8, NCHAN=8),))
    fds = FitsData(path)
    out = config.random_named_file(suffix=".fits")
    coord_names = [name for name in fds.coord_names if name != "FREQ"]
    data_slice = [3, slice(None), slice(None)]
    fds.write_to_fits(out, coord_names=coord_names, data_slice=data_slice, overwrite=True)

    with fits.open(out) as hdulist:
        assert hdulist[0].data.shape == (8, 8)
        beams = Table.read(hdulist[1])
        assert len(beams) == 1
        np.testing.assert_allclose(np.asarray(beams["BMAJ"]), np.linspace(0.4, 0.2, 8)[3:4])
        np.testing.assert_array_equal(np.asarray(beams["CHAN"]), [0])
        assert hdulist[1].header["NCHAN"] == 1


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


# --------------------------------------------------------------------------- hdu selection


def write_mef(config, npix=8, nchan=4, data=None, beams=None):
    """A file whose image lives in an extension, not the primary HDU."""
    if data is None:
        data = np.random.default_rng(9).normal(size=(nchan, npix, npix)).astype(np.float32)
    header = make_header(npix, nchan)
    header["BUNIT"] = "Jy/beam"
    hdus = [fits.PrimaryHDU(), fits.ImageHDU(data, header=header, name="SCI")]
    if beams is not None:
        hdus.append(beams)
    path = config.random_named_file(suffix=".fits")
    fits.HDUList(hdus).writeto(path, overwrite=True)
    return path, data


def test_hdu_selects_which_extension_carries_the_image(config):
    path, data = write_mef(config, npix=8, nchan=4)

    fds = FitsData(path, hdu=1)

    assert fds.hdu_index == 1
    assert fds.dshape == (4, 8, 8)
    assert fds.coord_names == ["FREQ", "DEC", "RA"]
    np.testing.assert_allclose(np.asarray(fds.data), data, rtol=1e-6)


def test_hdu_defaults_to_the_primary(config):
    fds = FitsData(write_fits(config, npix=8, nchan=2))
    assert fds.hdu_index == 0


@pytest.mark.filterwarnings("ignore::astropy.wcs.FITSFixedWarning")
def test_the_wrong_hdu_is_reported_not_guessed(config):
    """HDU 0 of an MEF carries no image; say so rather than limping on."""
    path, _ = write_mef(config)
    with pytest.raises(RuntimeError, match="does not match Image data"):
        FitsData(path)


def test_blocks_of_an_extension_read_from_that_extension(config):
    """The lazy graph has to carry the HDU index, not just the filename."""
    path, data = write_mef(config, npix=16, nchan=8)

    with dask.config.set({"array.chunk-size": "1kiB"}):
        fds = FitsData(path, hdu=1)
        assert fds.data.numblocks[0] > 1
        np.testing.assert_allclose(np.asarray(fds.data.blocks[2, 0, 0]), data[2:3], rtol=1e-6)


def test_beam_keywords_are_read_from_the_selected_hdu(config):
    """BMAJ lives on the image's own header, which is not HDU 0 here."""
    path, _ = write_mef(config, npix=8, nchan=1)
    with fits.open(path, mode="update") as hdulist:
        hdulist[1].header["BMAJ"] = 2e-3
        hdulist[1].header["BMIN"] = 1e-3
        hdulist[1].header["BPA"] = 20.0

    fds = FitsData(path, hdu=1)

    assert fds.beam_table is not None
    np.testing.assert_allclose(np.asarray(fds.beam_table["BMAJ"]), [2e-3])
    assert fds.beam_table_extname is None, "header keywords are not an extension"


def test_the_beam_table_after_the_image_wins(config):
    """With several images and several beam tables, ordering is all there is to go on.

    Scanning the file front to back regardless handed an image in extension 3 the
    beams belonging to extension 1.
    """
    header = make_header(8, nchan=4)
    path = config.random_named_file(suffix=".fits")
    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(np.zeros((4, 8, 8), np.float32), header=header, name="SCI1"),
            beam_hdu(4, name="BEAMS1"),
            fits.ImageHDU(np.zeros((4, 8, 8), np.float32), header=header, name="SCI2"),
            fits.BinTableHDU(
                Table({"BMAJ": np.full(4, 9.0), "BMIN": np.full(4, 9.0), "BPA": np.zeros(4)}),
                name="BEAMS2",
            ),
        ]
    ).writeto(path, overwrite=True)

    assert FitsData(path, hdu=1).beam_table_extname == "BEAMS1"
    second = FitsData(path, hdu=3)
    assert second.beam_table_extname == "BEAMS2"
    np.testing.assert_allclose(np.asarray(second.beam_table["BMAJ"]), 9.0)


def test_writing_an_extension_out_lands_in_a_primary_hdu(config):
    path, data = write_mef(config, npix=8, nchan=4)
    fds = FitsData(path, hdu=1)

    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, overwrite=True)

    with fits.open(out) as hdulist:
        assert [hdu.name for hdu in hdulist] == ["PRIMARY"]
    np.testing.assert_allclose(np.asarray(FitsData(out).data), data, rtol=1e-6)


# --------------------------------------------------------------------------- stacking


def test_expand_from_files_does_not_read_the_extra_file(config):
    """The extra files were pulled into memory whole by `da.asarray`."""
    first = write_fits(config, npix=64, nchan=32)
    second = write_fits(config, npix=64, nchan=32)

    fds = FitsData(first)
    fds.expand_along_axis_from_files("FREQ", [second])

    assert fds.dshape == (64, 64, 64)
    graph = len(pickle.dumps(dict(fds.data.dask)))
    assert graph < 8192, f"graph is {graph} bytes -- the extra file looks embedded in it"


def test_expand_from_files_continues_the_grid_in_world_units(config):
    """`pixel_size` is CDELT, in header units; the grid is in astropy's.

    On a cube whose CUNIT is not already SI the two differ by that factor, and
    stepping by the wrong one piles the appended channels on top of each other
    instead of continuing the band.
    """
    first = write_fits(config, npix=4, nchan=4, cunit3="MHz", cdelt3=1.0, crval3=1400.0)
    second = write_fits(config, npix=4, nchan=4, cunit3="MHz", cdelt3=1.0, crval3=1404.0)

    fds = FitsData(first)
    fds.expand_along_axis_from_files("FREQ", [second])

    grid = np.squeeze(np.asarray(fds.coords["FREQ"].data))
    np.testing.assert_allclose(grid, 1.4e9 + np.arange(8) * 1e6, rtol=1e-12)


def test_expand_keeps_the_grid_and_the_data_the_same_length(config):
    """`arange(start, stop, step)` takes its length from the endpoints.

    That is only reliable when `step` is exactly the grid's own spacing, and
    CDELT was not: it is a header value in header units, while the grid comes
    back off the WCS. Feed the one to the other and the count can come out one
    too many, leaving the coordinate grid and the data disagreeing about how
    many channels there are. Counting the values out instead removes the
    question rather than narrowing it.
    """
    # 1e6/3 over five channels is one such combination -- six coordinates for
    # the five channels being appended.
    fiddly = 1e6 / 3
    first = write_fits(config, npix=4, nchan=5, cdelt3=fiddly)
    second = write_fits(config, npix=4, nchan=5, cdelt3=fiddly)

    fds = FitsData(first)
    fds.expand_along_axis_from_files("FREQ", [second])

    grid = np.squeeze(np.asarray(fds.coords["FREQ"].data))
    assert grid.size == fds.dshape[0] == 10
    np.testing.assert_allclose(grid, 1.4e9 + np.arange(10) * fiddly, rtol=1e-9)


def test_expand_drops_the_beam_table_when_a_file_lacks_one(config, caplog):
    """A short table would now be written out as though it described the cube."""
    first = write_fits(config, npix=4, nchan=4, extra_hdus=(beam_hdu(4),))
    second = write_fits(config, npix=4, nchan=4)

    fds = FitsData(first)
    with caplog.at_level(logging.WARNING, logger="fitstoolz.reader"):
        fds.expand_along_axis_from_files("FREQ", [second])

    assert fds.beam_table is None
    assert fds.beam_table_extname is None
    assert "Dropping the beam table" in caplog.text

    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, overwrite=True)
    with fits.open(out) as hdulist:
        assert [hdu.name for hdu in hdulist] == ["PRIMARY"]


def test_expand_onto_a_cube_without_beams_does_not_crash(config):
    """Used to be an AttributeError: None has no add_row."""
    first = write_fits(config, npix=4, nchan=4)
    second = write_fits(config, npix=4, nchan=4, extra_hdus=(beam_hdu(4),))

    fds = FitsData(first)
    fds.expand_along_axis_from_files("FREQ", [second])

    assert fds.dshape[0] == 8
    assert fds.beam_table is None


# --------------------------------------------------------------------------- header units


def test_write_preserves_a_non_si_spectral_unit(config):
    """CUNIT was taken off the grid while CDELT was taken off the header.

    That described a cube in MHz as one in Hz and left CDELT at its MHz value --
    a channel width a million times too narrow, and no round trip.
    """
    path = write_fits(config, npix=4, nchan=4, cunit3="MHz", cdelt3=1.0, crval3=1400.0)
    fds = FitsData(path)

    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, overwrite=True)

    header = fits.getheader(out)
    assert header["CUNIT3"] == "MHz"
    np.testing.assert_allclose(header["CRVAL3"], 1400.0, rtol=1e-12)
    np.testing.assert_allclose(header["CDELT3"], 1.0, rtol=1e-12)

    np.testing.assert_allclose(
        np.squeeze(np.asarray(FitsData(out).coords["FREQ"].data)),
        np.squeeze(np.asarray(fds.coords["FREQ"].data)),
        rtol=1e-12,
    )


def test_to_unit_converts_or_passes_through():
    assert reader.to_unit(1.0, "MHz", "Hz") == 1e6
    assert reader.to_unit(3.0, "Hz", "Hz") == 3.0
    assert reader.to_unit(3.0, "", "Hz") == 3.0, "a unitless axis is ordinary, not an error"
    assert reader.to_unit(3.0, "Hz", None) == 3.0
    assert reader.to_unit(3.0, "Hz", "deg") == 3.0, "incompatible units pass through rather than raise"


# --------------------------------------------------------------------------- the reference pixel


def assert_wcs_follows_the_data(source, written, data_slice):
    """Every written pixel must carry the world coordinates of the pixel it came from.

    This is the property the whole CRPIX/CRVAL path exists to hold, and the one a
    keyword-by-keyword comparison keeps missing: a slice renumbers the pixels, so
    the keywords are *supposed* to differ.
    """
    with fits.open(source) as hdulist:
        src_header, src_shape = hdulist[0].header, hdulist[0].data.shape
    with fits.open(written) as hdulist:
        out_header, out_shape = hdulist[0].header, hdulist[0].data.shape

    resolved = [item.indices(length) for item, length in zip(data_slice, src_shape)]
    starts = np.array([start for start, _, _ in resolved])
    steps = np.array([step for _, _, step in resolved])

    out_pixels = np.indices(out_shape).reshape(len(out_shape), -1).T
    src_pixels = out_pixels * steps + starts

    np.testing.assert_allclose(
        WCS(out_header).wcs_pix2world(out_pixels[:, ::-1].astype(float), 0),
        WCS(src_header).wcs_pix2world(src_pixels[:, ::-1].astype(float), 0),
        atol=1e-12,
    )


@pytest.mark.parametrize(
    "data_slice",
    [
        [slice(None), slice(None), slice(None)],
        [slice(2, 5), slice(None), slice(None)],
        [slice(6, None), slice(None), slice(None)],
        [slice(-3, None), slice(None), slice(None)],
        [slice(None, None, 2), slice(None), slice(None)],
        [slice(None), slice(2, 6), slice(1, 7)],
    ],
)
def test_a_slice_moves_the_reference_pixel_with_the_data(config, data_slice):
    """`slice` wrote the unsliced reference, mislabelling every channel by start*CDELT.

    The beam table was being cut by the same slice correctly, so the output
    disagreed with itself about which channels it held.
    """
    path = write_fits(config, npix=8, nchan=8)
    out = config.random_named_file(suffix=".fits")
    FitsData(path).write_to_fits(out, data_slice=data_slice, overwrite=True)
    assert_wcs_follows_the_data(path, out, data_slice)


def test_a_strided_slice_widens_cdelt(config):
    path = write_fits(config, npix=4, nchan=8)
    out = config.random_named_file(suffix=".fits")
    FitsData(path).write_to_fits(out, data_slice=[slice(None, None, 2), slice(None), slice(None)], overwrite=True)

    header = fits.getheader(out)
    assert header["NAXIS3"] == 4
    np.testing.assert_allclose(header["CDELT3"], 2 * make_header(4, nchan=8)["CDELT3"])


@pytest.mark.parametrize("crpix3", [-2, 0, 1, 5, 40])
def test_a_reference_pixel_outside_the_data_round_trips(config, crpix3):
    """CRPIX need not land inside the array: cutouts and mosaic facets put it outside.

    CRVAL was read out of the coordinate grid by indexing it with CRPIX, which
    raised IndexError above the array and wrapped round to the far end below it.
    """
    header = make_header(4, nchan=4)
    header["CRPIX3"] = crpix3
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((4, 4, 4), np.float32), header=header).writeto(path, overwrite=True)

    out = config.random_named_file(suffix=".fits")
    FitsData(path).write_to_fits(out, overwrite=True)
    assert_wcs_follows_the_data(path, out, [slice(None)] * 3)


def test_a_reference_pixel_outside_the_data_still_scales_a_header_beam(config):
    """The single-beam expansion indexed the grid by CRPIX too, so the file would not open."""
    header = make_header(4, nchan=4)
    header["CRPIX3"] = 40
    header["BMAJ"], header["BMIN"], header["BPA"] = 1e-3, 5e-4, 0.0
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((4, 4, 4), np.float32), header=header).writeto(path, overwrite=True)

    fds = FitsData(path)
    freqs = np.squeeze(np.asarray(fds.coords["FREQ"].data))
    # The reference frequency is extrapolated to pixel 39, well past the 4 channels.
    ref_freq = freqs[0] + (freqs[1] - freqs[0]) * 39
    np.testing.assert_allclose(np.asarray(fds.beam_table["BMAJ"]), 1e-3 * ref_freq / freqs, rtol=1e-9)


def test_a_half_pixel_reference_is_not_snapped_to_a_whole_one(config):
    """CRPIX 32.5 is what an image phase-centred between pixels carries.

    `int(CRPIX) - 1` moved the reference onto its neighbour, and the write put
    that back on disk.
    """
    header = make_header(8, nchan=2)
    header["CRPIX1"] = header["CRPIX2"] = 4.5
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(np.zeros((2, 8, 8), np.float32), header=header).writeto(path, overwrite=True)

    fds = FitsData(path)
    assert fds.coords["RA"].ref_pixel == 3.5

    out = config.random_named_file(suffix=".fits")
    fds.write_to_fits(out, overwrite=True)
    written = fits.getheader(out)
    assert written["CRPIX1"] == 4.5
    np.testing.assert_allclose(written["CRVAL1"], RA0, rtol=1e-12)
    assert_wcs_follows_the_data(path, out, [slice(None)] * 3)


def test_a_whole_reference_pixel_stays_an_integer(config):
    """`ref_pixel` is still usable as an index when CRPIX is a whole pixel."""
    fds = FitsData(write_fits(config, npix=8, nchan=4))
    assert isinstance(fds.coords["FREQ"].ref_pixel, int)
    assert isinstance(fds.coords["RA"].ref_pixel, int)


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


def test_a_scaled_image_opens_at_the_default_memmap(config):
    """astropy will not scale a memory-mapped image, so opening one used to raise.

    `FitsData(path)` defaults to memmap=True and the dtype sniff went through
    that handle, so a BSCALE/BZERO cube could not be opened at all -- only
    `memmap=False` worked, which nothing said.
    """
    raw = np.arange(2 * 8 * 8, dtype=np.int16).reshape(2, 8, 8)
    header = make_header(8, nchan=2)
    header["BZERO"], header["BSCALE"] = 100.0, 0.5
    path = config.random_named_file(suffix=".fits")
    fits.PrimaryHDU(raw, header=header).writeto(path, overwrite=True)

    expected = fits.getdata(path)
    with FitsData(path) as fds:  # memmap=True, the default
        np.testing.assert_allclose(np.asarray(fds.data), expected, rtol=1e-6)
        # `get_data` reads through the handle rather than the graph, so it has to
        # have been reopened rather than merely worked around.
        np.testing.assert_allclose(np.asarray(fds.get_data()), expected, rtol=1e-6)

    out = config.random_named_file(suffix=".fits")
    FitsData(path).write_to_fits(out, overwrite=True)
    np.testing.assert_allclose(fits.getdata(out), expected, rtol=1e-6)


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
