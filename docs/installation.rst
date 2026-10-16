.. _installation:

Installation
============

Requirements
------------

* Python 3.11 or newer (and older than 3.14)
* astropy 7.x, numpy 2.x, dask and xarray — installed for you by pip

From PyPI
---------

.. code-block:: console

    $ pip install fitstoolz

From GitHub
-----------

To install the latest development version:

.. code-block:: console

    $ pip install git+https://github.com/shinobi-dosho/fitstoolz

Either way, this installs:

* the ``fitstoolz`` command-line tool, and
* the importable ``fitstoolz`` package.

For development
---------------

The project uses `uv <https://docs.astral.sh/uv/>`_:

.. code-block:: console

    $ git clone https://github.com/shinobi-dosho/fitstoolz
    $ cd fitstoolz
    $ uv sync --group dev
    $ uv run --group tests python -m pytest
    $ uv run --group ruff ruff check src tests docs

    $ git config core.hooksPath .githooks   # enable the repo's pre-commit hook

``uv.lock`` is committed, so ``uv sync`` gives you the same dependency versions
CI tests against (it runs every job with ``--locked``). Change
``pyproject.toml`` and you must re-run ``uv lock`` and commit both; the repo's
pre-commit hook and CI each reject the mismatch.

That the *pinned* astropy is the one under test matters more than usual here —
see :doc:`security` for why. ``CONTRIBUTING.md`` has the full workflow.

To build the documentation locally:

.. code-block:: console

    $ uv sync --group docs
    $ uv run sphinx-build -b html docs docs/_build/html
    $ open docs/_build/html/index.html

Optional workflow integration
-----------------------------

The base installation includes the library and all seven native commands.
``unstack`` splits a named axis into numbered, length-one FITS outputs under
the required ``--output-prefix``; see :doc:`cli` for output naming and overwrite
behavior.

To use the existing Python steps in Ninja recipes or dosho:

.. code-block:: console

    $ uv pip install 'fitstoolz[ninja]'
    $ ninja run fitstoolz.apps.stats:stats --help

Named step exports and each module's ``step`` alias are loaded lazily. The
``slice`` module retains the name ``slice_``. A missing Ninja installation
produces an error explaining how to install the extra. The extra supports
released ``stimela-ninja>=0.1.0b5``; development no longer overrides it with a
floating Git checkout.

Run optional integration tests with:

.. code-block:: console

    $ uv run --extra ninja --group tests python -m pytest tests/test_ninja.py
