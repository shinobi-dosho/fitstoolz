==========
fitstoolz
==========

|docs| |license| |python|

Python libraries and command-line tools for interfacing with FITS data in an
intuitive way.

FITS numbers its axes from one and writes them fastest-varying-first; numpy does
neither. fitstoolz reads the WCS once, gives every axis a **name**, and lets you
use that name everywhere — on the data, on the coordinates, and on the command
line — so you never have to work out which convention applies where.

Features
--------

* Image and coordinate data indexing is consistent
* Simple API for adding, transposing and expanding axes (or dimensions)
* Celestial, spectral and Stokes axes evaluated through the WCS rather than
  approximated by stepping ``CDELT``
* `Xarray support <https://docs.xarray.dev/en/stable/index.html>`_
* `Zarr support <https://zarr.readthedocs.io/en/stable/index.html>`_
* A ``fitstoolz`` command line whose subcommands double as
  `stimela-ninja <https://github.com/shinobi-dosho/stimela-ninja>`_ pipeline steps

Installation
------------

.. code-block:: console

    $ pip install fitstoolz

Requires Python 3.11–3.13. See the `installation docs
<https://fitstoolz.readthedocs.io/en/latest/installation.html>`_ for the
development setup.

Example Usage
-------------

.. code-block:: ipython

    In[1]: from fitstoolz.reader import FitsData

    In[2]: myfits = FitsData("example-image.fits")
           myfits.coord_names

    Out[2]: ['STOKES', 'FREQ', 'DEC', 'RA']

    In[3]: myfits.dshape
    Out[3]: (1, 504, 100, 100) # these dimensions match the labels above

    In[4]: myfits.coords

    Out[4]:
    Coordinates:
    STOKES   (stokes) int32 4B dask.array<chunksize=(1,), meta=np.ndarray>
    FREQ     (spectral) float64 4kB 8.803e+08 8.804e+08 ... 9.328e+08 9.329e+08
    RA       (celestial.ra) float64 800B 53.16 53.16 53.16 ... 53.1 53.1 53.1
    DEC      (celestial.dec) float64 800B -28.16 -28.16 ... -28.11 -28.11

From the command line:

.. code-block:: console

    $ fitstoolz header image.fits --show
    $ fitstoolz stats image.fits --show
    $ fitstoolz slice image.fits --axis FREQ,0,64 --outfile cube-sub.fits

Documentation
-------------

Full documentation is at `fitstoolz.readthedocs.io
<https://fitstoolz.readthedocs.io>`_ — including a `quickstart
<https://fitstoolz.readthedocs.io/en/latest/quickstart.html>`_ and the generated
`command-line reference <https://fitstoolz.readthedocs.io/en/latest/cli.html>`_.

Contributing
------------

Bug reports, fixes, tests and documentation are all welcome. See
`CONTRIBUTING.md <CONTRIBUTING.md>`_ for the development setup, and
`AGENTS.md <AGENTS.md>`_ for the design conventions — particularly if your
change touches axis ordering or adds a new app. By participating you agree to
the `Code of Conduct <CODE_OF_CONDUCT.md>`_.

Security
--------

A FITS file is untrusted input. `SECURITY.md <SECURITY.md>`_ describes what
fitstoolz does and does not guarantee about hostile or malformed ones, and how
to report a vulnerability privately — **please don't open a public issue for
security problems**.

License
-------

MIT — see `LICENSE <LICENSE>`_.

.. |docs| image:: https://readthedocs.org/projects/fitstoolz/badge/?version=latest
    :target: https://fitstoolz.readthedocs.io/en/latest/
    :alt: Documentation status

.. |license| image:: https://img.shields.io/badge/license-MIT-blue.svg
    :target: LICENSE
    :alt: MIT license

.. |python| image:: https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg
    :target: https://pypi.org/project/fitstoolz/
    :alt: Supported Python versions
