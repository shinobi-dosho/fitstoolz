"""Unstack keeps each selected pixel's data, coordinates, and beam rows."""

from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from click.testing import CliRunner

from fitstoolz.apps.main import cli
from fitstoolz.apps.unstack import UnstackOutputs, _unstack, inputs_model, runit
from fitstoolz.reader import FitsData
from fitstoolz.utils import open_fits

from .test_reader import beam_hdu, make_header


@pytest.fixture
def cube(tmp_path):
    data = np.arange(3 * 3 * 4 * 4, dtype=np.float32).reshape(3, 3, 4, 4)
    header = make_header(4, nchan=3, nstokes=3, cunit3="MHz", cdelt3=-2, crval3=1400)
    header["CRPIX1"] = 2.5
    header["CRPIX3"] = 8.5
    header["CRPIX4"], header["CRVAL4"] = 2, 2
    path = tmp_path / "input.fits"
    fits.HDUList([fits.PrimaryHDU(data, header), beam_hdu(3)]).writeto(path)
    return path, data


@pytest.mark.parametrize("axis", ["FREQ", "STOKES", "RA", "DEC"])
def test_unstack_data_world_coordinates_and_outputs(cube, tmp_path, axis):
    path, data = cube
    prefix = tmp_path / "plane.fits"
    inputs = inputs_model(fname=str(path), axis=axis, output_prefix=str(prefix), ra_chunks=2, spectral_chunks=1)
    result = _unstack(**inputs.model_dump())
    assert isinstance(result, UnstackOutputs)
    with FitsData(path) as source:
        idx = source.coord_index(axis)
        outputs = result.unstacked_fits
        assert outputs == [str(tmp_path / f"plane-{pixel:04d}.fits") for pixel in range(data.shape[idx])]
        for pixel, output in enumerate(outputs):
            selection = [slice(None)] * data.ndim
            selection[idx] = slice(pixel, pixel + 1)
            expected = data[tuple(selection)]
            with open_fits(output) as hdus:
                np.testing.assert_array_equal(hdus[0].data, expected)
                assert hdus[0].header["CUNIT3"] == "MHz"
                # Compare every output pixel against the corresponding input
                # pixel through the full WCS, including coupled sky axes.
                output_pixels = np.indices(expected.shape).reshape(data.ndim, -1).T[:, ::-1]
                input_pixels = output_pixels.copy()
                input_pixels[:, data.ndim - idx - 1] += pixel
                np.testing.assert_allclose(
                    WCS(hdus[0].header).all_pix2world(output_pixels, 0),
                    source.wcs.all_pix2world(input_pixels, 0),
                )
                expected_beams = source.beam_table[pixel : pixel + 1] if axis == "FREQ" else source.beam_table
                np.testing.assert_allclose(hdus[1].data["BMAJ"], expected_beams["BMAJ"])
                np.testing.assert_array_equal(hdus[1].data["CHAN"], np.arange(len(expected_beams)))
            with FitsData(output) as reopened:
                assert reopened.coord_names == source.coord_names
                assert reopened.dshape[idx] == 1
                expected_stokes = source.coords["STOKES"].values
                if axis == "STOKES":
                    expected_stokes = expected_stokes[pixel : pixel + 1]
                np.testing.assert_allclose(reopened.coords["STOKES"].values, expected_stokes)


def test_unstack_cli_overwrites_explicit_prefix(cube, tmp_path):
    path, data = cube
    (tmp_path / "channel-0000.fits").write_bytes(b"old output")
    result = CliRunner().invoke(
        cli, ["unstack", str(path), "--axis", "FREQ", "--output-prefix", str(tmp_path / "channel")]
    )
    assert result.exit_code == 0, result.output
    with open_fits(tmp_path / "channel-0000.fits") as hdus:
        np.testing.assert_array_equal(hdus[0].data, data[:, :1])


@pytest.mark.parametrize("missing", ["axis", "output_prefix"])
def test_unstack_cli_requires_axis_and_prefix(cube, tmp_path, missing):
    args = ["unstack", str(cube[0])]
    if missing != "axis":
        args += ["--axis", "FREQ"]
    if missing != "output_prefix":
        args += ["--output-prefix", str(tmp_path / "channel")]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "Missing option" in result.output
    assert not list(tmp_path.glob("channel-*.fits"))


def options(path, prefix, axis="FREQ"):
    return SimpleNamespace(
        fname=str(path), output_prefix=str(prefix), axis=axis, ra_chunks=None, dec_chunks=None, spectral_chunks=None
    )


@pytest.mark.parametrize("alias", ["path", "symlink", "hardlink"])
def test_unstack_preflights_all_outputs_against_input(cube, tmp_path, alias):
    source, _ = cube
    destination = tmp_path / "plane-0002.fits"
    if alias == "path":
        source.rename(destination)
        source = destination
    elif alias == "symlink":
        destination.symlink_to(source)
    else:
        destination.hardlink_to(source)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="overwrite the input"):
        runit(options(source, tmp_path / "plane"))
    assert source.read_bytes() == original
    assert not (tmp_path / "plane-0000.fits").exists()
    assert not (tmp_path / "plane-0001.fits").exists()


def test_unstack_invalid_axis_writes_nothing(cube, tmp_path):
    with pytest.raises(ValueError):
        runit(options(cube[0], tmp_path / "plane", axis="NOEXIST"))
    assert not list(tmp_path.glob("plane-*.fits"))


@pytest.mark.parametrize("crpix", [2, 2.5, 40, -4])
def test_stokes_reference_is_a_coordinate(cube, crpix):
    path, _ = cube
    with open_fits(path, mode="update") as hdus:
        hdus[0].header["CRPIX4"] = crpix
    with FitsData(path) as source:
        expected = 2 + (np.arange(3) - (crpix - 1))
        np.testing.assert_allclose(source.coords["STOKES"].values, expected)
