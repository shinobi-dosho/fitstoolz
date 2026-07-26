fitstoolz
=========

Python libraries and command-line tools for interfacing with FITS data in an
intuitive way.

FITS numbers its axes from one and writes them fastest-varying-first; numpy does
neither. fitstoolz reads the WCS once, gives every axis a **name**, and lets you
use that name everywhere — on the data, on the coordinates, and on the command
line — so you never have to work out which convention applies where.

.. note::

   Early beta. The interfaces documented here are real and tested, but they may
   still change between ``0.x`` releases.

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

.. code-block:: console

    $ fitstoolz stats image.fits --show


.. toctree::
   :maxdepth: 2
   :caption: Getting started

   installation
   quickstart

.. toctree::
   :maxdepth: 2
   :caption: Using fitstoolz

   cli

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api/index

.. toctree::
   :maxdepth: 2
   :caption: Project

   security
   contributing


Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
