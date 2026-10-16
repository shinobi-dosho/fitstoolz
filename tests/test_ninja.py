"""Optional workflow integration; run with uv run --extra ninja --group tests python -m pytest tests/test_ninja.py."""

import importlib
from typing import get_type_hints

import pytest
from click.testing import CliRunner

pytest.importorskip("shinobi")

from shinobi.cli import main as ninja_cli
from shinobi.clickutil import build_options as ninja_options

from fitstoolz.apps import main as main_group
from fitstoolz.apps._cli import build_options
from fitstoolz.reader import FitsData

from . import InitTest


@pytest.fixture
def config(monkeypatch):
    files = InitTest()
    monkeypatch.chdir(files.random_named_directory())
    return files


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


@pytest.mark.parametrize("module_name", main_group.applist)
def test_lazy_aliases_and_schema(module_name, config):
    module = importlib.import_module(f"fitstoolz.apps.{module_name}")
    public_name = "slice_" if module_name == "slice" else module_name
    adapter = getattr(module, public_name)
    assert module.step is adapter
    assert module.step.step.name == module.app
    assert set(adapter.step.outputs_model.model_fields) == set(
        get_type_hints(getattr(module, "_" + module_name))["return"].model_fields
    )
    native = build_options(module.inputs_model)
    workflow = ninja_options(adapter.step.inputs_model)
    assert [(opt.name, opt.opts, opt.secondary_opts, opt.multiple, opt.default) for opt in native] == [
        (opt.name, opt.opts, opt.secondary_opts, opt.multiple, opt.default) for opt in workflow
    ]


def test_ninja_run_and_provenance(config):
    from pathlib import Path

    result = CliRunner().invoke(
        ninja_cli,
        ["run", "fitstoolz.apps.stats:stats", "--provenance", "--no-cache", "--fname", config.example_fits_file()],
    )
    assert result.exit_code == 0, result.output
    assert list(Path.cwd().glob(".shinobi/runs/**/*.json"))


def test_step_cache_returns_same_typed_outputs(config):
    from fitstoolz.apps.stats import stats

    kwargs = {"fname": config.example_fits_file(), "cache": True, "cache_dir": config.random_named_directory()}
    first = stats(**kwargs)
    second = stats(**kwargs)
    assert first.success and second.success
    assert second.cached
    assert second.outputs == first.outputs
