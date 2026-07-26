"""Sphinx configuration for the fitstoolz documentation.

Autodoc imports the ``fitstoolz`` package, so the build environment must have it
installed (``uv sync --group docs`` locally; Read the Docs installs it via
``.readthedocs.yaml``). The package lives under ``src/``, added to sys.path
below so an editable/uninstalled checkout also builds.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath("../src"))

import fitstoolz  # noqa: E402

# -- Project information -----------------------------------------------------

project = "fitstoolz"
author = "Sphesihle Makhathini"
maintainer = "Mika Naidoo, Athanaseus Ramaila"
copyright = f"{datetime.now(tz=timezone.utc).year}, {author}"

version = fitstoolz.__version__
release = fitstoolz.__version__

language = "en"

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinx_click",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

nitpicky = False

# -- Autodoc / autosummary ---------------------------------------------------

autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
    "undoc-members": False,
}
# pydantic BaseModels carry a lot of inherited machinery; don't document it.
autodoc_inherit_docstrings = False

napoleon_google_docstring = True
napoleon_numpy_docstring = True
# Render Google-style "Attributes:" sections as an :ivar: field list on the
# class docstring instead of standalone `.. attribute::` directives -- the
# latter collides with autodoc's own scan of annotated class attributes,
# producing "duplicate object description" warnings.
napoleon_use_ivar = True

# -- Intersphinx -------------------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "astropy": ("https://docs.astropy.org/en/stable/", None),
    "xarray": ("https://docs.xarray.dev/en/stable/", None),
    "dask": ("https://docs.dask.org/en/stable/", None),
}

# -- HTML output -------------------------------------------------------------

html_theme = "furo"
html_title = f"fitstoolz {release}"
html_static_path = ["_static"]

html_theme_options = {
    "source_repository": "https://github.com/shinobi-dosho/fitstoolz/",
    "source_branch": "main",
    "source_directory": "docs/",
}

# -- MyST (markdown) ---------------------------------------------------------

myst_enable_extensions = ["colon_fence", "deflist"]
