import importlib

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from click.testing import CliRunner

from fitstoolz.apps import main as main_group
from fitstoolz.apps import outfits_name
from fitstoolz.reader import FitsData

from . import InitTest


@pytest.fixture
def config():
    return InitTest()


def test_help_display():
    runner = CliRunner()
    result = runner.invoke(main_group.cli, "--help")
    assert result.exit_code == 0
    for app in main_group.app_dict:
        result = runner.invoke(main_group.cli, f"{app} --help")
        assert result.exit_code == 0


def test_header(config: InitTest):
    image_file = config.example_fits_file()
    runner = CliRunner()

    result = runner.invoke(main_group.cli, f"header --show {image_file}")
    assert result.exit_code == 0

    outfits = config.random_named_file(suffix=".fits")
    result = runner.invoke(main_group.cli, f"header --add Foo=bar --outfile {outfits} {image_file}")

    assert result.exit_code == 0

    result = runner.invoke(main_group.cli, f"header --edit Foo=23 --outfile {outfits} {image_file}")

    assert result.exit_code == 0

    result = runner.invoke(main_group.cli, f"header --remove Foo --replace {outfits}")

    assert result.exit_code == 0


def test_header_no_outfile_error(config: InitTest):
    image_file = config.example_fits_file()
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"header --add Foo=bar {image_file}")
    assert result.exit_code != 0


def test_add_remove_axis(config: InitTest):
    image_file = config.example_fits_file()
    runner = CliRunner()

    result = runner.invoke(
        main_group.cli,
        f"add-axis --ctype STOKES --index 4 --crpix 0 --crval 1 --cdelt 1 --cunit Jy --replace {image_file}",
    )
    assert result.exit_code == 0

    myfits = FitsData(image_file)
    assert myfits.ndim == 4
    assert "STOKES" in myfits.coord_names
    myfits.close()
    result = runner.invoke(main_group.cli, f"remove-axis --ctype STOKES --replace {image_file}")
    assert result.exit_code == 0

    myfits = FitsData(image_file)
    assert myfits.ndim == 3
    assert "STOKES" not in myfits.coord_names
    myfits.close()


def test_add_axis_duplicate_error(config: InitTest):
    image_file = config.example_fits_file()
    runner = CliRunner()

    result = runner.invoke(
        main_group.cli,
        f"add-axis --ctype FREQ --index 4 --crpix 0 --crval 1 --cdelt 1 --cunit Hz --replace {image_file}",
    )
    assert result.exit_code != 0


def test_remove_axis_missing_error(config: InitTest):
    image_file = config.example_fits_file()
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"remove-axis --ctype NOEXIST --replace {image_file}")
    assert result.exit_code != 0


def test_stats(config: InitTest):
    image_file = config.example_fits_file()
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"stats {image_file}")
    assert result.exit_code == 0


def test_slice(config: InitTest):
    image_file = config.example_fits_file()
    outfits = config.random_named_file(suffix=".fits")
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"slice --outfile {outfits} {image_file}")
    assert result.exit_code == 0

    myfits = FitsData(outfits)
    assert myfits.ndim == 3
    myfits.close()


def test_stack(config: InitTest):
    pix_size = 5 / 3600
    npix = 128
    dfreq = 1e6
    freq0 = 1.4e9
    wcs = WCS(naxis=3)
    wcs.wcs.ctype = ["RA---SIN", "DEC--SIN", "FREQ"]
    wcs.wcs.cdelt = np.array([-pix_size, pix_size, dfreq])
    wcs.wcs.crpix = [npix / 2, npix / 2, 1]
    wcs.wcs.crval = [2.0, -30, freq0]
    wcs.wcs.cunit = ["deg", "deg", "Hz"]
    header = wcs.to_header()

    filenames = []
    for nchan in [2, 3]:
        image = np.random.randn(nchan, npix, npix).astype(np.float32)
        hdu = fits.PrimaryHDU(image, header=header)
        hdul = fits.HDUList([hdu])
        fname = config.random_named_file(suffix=".fits")
        hdul.writeto(fname, overwrite=True)
        hdul.close()
        filenames.append(fname)

    outfits = config.random_named_file(suffix=".fits")
    runner = CliRunner()
    result = runner.invoke(
        main_group.cli, f"stack --axis FREQ --stacked-fits {outfits} --extra-files {filenames[1]} {filenames[0]}"
    )
    assert result.exit_code == 0

    myfits = FitsData(outfits)
    assert myfits.ndim == 3
    assert myfits.dshape[0] == 5
    myfits.close()


def test_outfits_name_outfile():
    result = outfits_name("/in.fits", "/out.fits")
    assert result == "/out.fits"


def test_outfits_name_replace():
    result = outfits_name("/in.fits", None, replace=True)
    assert result == "/in.fits"


def test_outfits_name_raise():
    with pytest.raises(RuntimeError, match="Both --replace and --outfile"):
        outfits_name("/in.fits", None, raise_exception=True)


def test_outfits_name_none():
    result = outfits_name("/in.fits", None)
    assert result is None


def test_app_inputs_models():
    """Every app is a shinobi pystep whose signature is the schema authority."""
    for app_name, import_path in main_group.app_dict.items():
        modname = import_path.rsplit(".", 1)[0]
        mod = importlib.import_module(modname)
        step = mod.step
        assert step.step.name == app_name
        fields = step.step.inputs_model.model_fields
        assert fields["fname"].is_required()
        assert "log_level" in fields


def test_unstack_not_implemented(config: InitTest):
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"unstack --axis FREQ {config.example_fits_file()}")
    assert result.exit_code != 0
    assert isinstance(result.exception, NotImplementedError)


def test_apps_chain_in_a_recipe(config: InitTest):
    """Two apps wired into a shinobi Recipe: add-axis' output path feeds remove-axis."""
    from pydantic import BaseModel
    from shinobi import Recipe

    from fitstoolz.apps import FitsOutputs
    from fitstoolz.apps.add_axis import add_axis
    from fitstoolz.apps.remove_axis import remove_axis

    class ChainInputs(BaseModel):
        fname: str
        mid: str
        final: str

    chain = Recipe(name="chain", inputs_model=ChainInputs, outputs_model=FitsOutputs)
    chain.add_step("add", add_axis, fname=chain.inputs.fname, ctype="STOKES", index=4, outfile=chain.inputs.mid)
    chain.add_step("remove", remove_axis, fname=chain.outputs.add.outfile, ctype="STOKES", outfile=chain.inputs.final)
    chain.set_output("outfile", chain.outputs.remove.outfile)

    mid = config.random_named_file(suffix=".fits")
    final = config.random_named_file(suffix=".fits")
    result = chain(fname=config.example_fits_file(), mid=mid, final=final)

    assert result.success
    assert result.outputs.outfile == final

    myfits = FitsData(mid)
    assert "STOKES" in myfits.coord_names
    myfits.close()

    myfits = FitsData(final)
    assert "STOKES" not in myfits.coord_names
    myfits.close()


def test_stats_step_returns_outputs(config: InitTest):
    """A pystep run outside click returns its typed outputs."""
    from fitstoolz.apps.stats import stats

    result = stats(fname=config.example_fits_file())
    assert result.success
    assert result.outputs.std > 0
    assert result.outputs.min <= result.outputs.mean <= result.outputs.max


def test_stats_show_slice_and_clipping(config: InitTest):
    """Exercise --show, --slice and both clip options with an explicit blank value."""
    image_file = config.example_fits_file()
    runner = CliRunner()
    result = runner.invoke(
        main_group.cli,
        f"stats --show --slice FREQ,0,1 --clip-below -0.5 --clip-above 0.5 --blank-value 0 {image_file}",
    )
    assert result.exit_code == 0, result.output


def test_stats_clipping_defaults_to_nan_blank(config: InitTest):
    image_file = config.example_fits_file()
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"stats --show --clip-below 0 {image_file}")
    assert result.exit_code == 0, result.output


def test_stats_unknown_slice_axis_errors(config: InitTest):
    image_file = config.example_fits_file()
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"stats --slice TIME,0,1 {image_file}")
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "Unknown axis 'TIME'" in str(result.exception)


def test_slice_along_the_spectral_axis(config: InitTest):
    """--axis CTYPE,START,END must trim the cube."""
    image_file = config.example_fits_file()  # (2, 128, 128)
    outfits = config.random_named_file(suffix=".fits")
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"slice --axis FREQ,0,1 --outfile {outfits} {image_file}")
    assert result.exit_code == 0, result.output

    myfits = FitsData(outfits)
    assert myfits.dshape[0] == 1
    myfits.close()


def test_slice_unknown_axis_errors(config: InitTest):
    image_file = config.example_fits_file()
    outfits = config.random_named_file(suffix=".fits")
    runner = CliRunner()
    result = runner.invoke(main_group.cli, f"slice --axis TIME,0,1 --outfile {outfits} {image_file}")
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "Unknown axis 'TIME'" in str(result.exception)
