"""The base installation has native applications without the workflow adapter."""

import subprocess
import sys

from . import InitTest


def test_native_apps_without_shinobi():
    files = InitTest()
    code = """
import importlib.abc
import importlib
import sys
class NoShinobi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "shinobi" or fullname.startswith("shinobi."):
            raise ModuleNotFoundError("blocked optional dependency", name="shinobi")
sys.meta_path.insert(0, NoShinobi())
from click.testing import CliRunner
from fitstoolz.apps.main import cli, applist
from fitstoolz.reader import FitsData
runner = CliRunner()
assert runner.invoke(cli, ["--help"]).exit_code == 0
for name in applist:
    module = importlib.import_module("fitstoolz.apps." + name)
    assert callable(module.runit)
    result = runner.invoke(cli, [name.replace("_", "-"), "--help"])
    assert result.exit_code == 0, result.output
for args in (["stats", "--show", sys.argv[1]], ["header", "--show", sys.argv[1]]):
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, (result.output, result.exception)
assert "shinobi" not in sys.modules
try:
    importlib.import_module("fitstoolz.apps.stats").step
except ImportError as exc:
    assert "fitstoolz[ninja]" in str(exc)
else:
    raise AssertionError("workflow adapter loaded without shinobi")
"""
    result = subprocess.run([sys.executable, "-c", code, files.example_fits_file()], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
