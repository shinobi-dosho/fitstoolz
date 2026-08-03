.. _quickstart:

Quickstart
==========

Everything in fitstoolz addresses axes **by name**. Open a file, ask what its
axes are called, and use those names from then on.

Reading a FITS file
-------------------

:class:`~fitstoolz.reader.FitsData` wraps an astropy ``HDUList`` and its WCS,
and exposes the axes as named coordinates:

.. code-block:: python

    from fitstoolz.reader import FitsData

    with FitsData("example-image.fits") as myfits:
        print(myfits.coord_names)   # ['STOKES', 'FREQ', 'DEC', 'RA']
        print(myfits.dshape)        # (1, 504, 100, 100) -- same order
        print(myfits.dims)          # ['stokes', 'spectral', 'celestial.dec', 'celestial.ra']

``coord_names`` and ``dshape`` are in the **same order**, which is numpy's, not
FITS's. That is the point: ``dshape[myfits.coord_index("FREQ")]`` is the number
of channels, and you never touch a ``NAXISn`` number.

Two vocabularies are in play, and they are not interchangeable:

``coord_names``
    The FITS axis names — ``RA``, ``DEC``, ``FREQ``, ``STOKES``. This is what
    you pass to fitstoolz.

``dims``
    The xarray dimension labels — ``celestial.ra``, ``spectral``, ``stokes``.
    These appear in the xarray objects you get back.

Methods that take user input accept coordinate names and translate for you.

Coordinates
-----------

``myfits.coords`` is an :class:`xarray.Coordinates` built by evaluating the WCS,
so the values are true world coordinates rather than a ``CRVAL + n*CDELT``
approximation:

.. code-block:: python

    myfits.coords["FREQ"].values      # channel frequencies, in Hz
    myfits.coords["RA"].attrs         # {'name', 'pixel_size', 'dim', 'ref_pixel', 'units', 'size'}
    myfits.coords["RA"].ref_pixel     # 0-based, unlike the CRPIX on disk

Celestial axes are sampled through the reference pixel of the *other* celestial
axis, because a projected sky grid is not separable — a pixel's longitude
depends on its latitude. Stepping right ascension by ``CDELT`` would be wrong by
``1/cos(dec)``.

Getting an xarray DataArray
---------------------------

.. code-block:: python

    xds = myfits.get_xds(chunks={"RA": 64, "DEC": 64})
    xds = myfits.get_xds(transpose=["RA", "DEC", "FREQ", "STOKES"])

Both ``chunks`` and ``transpose`` accept coordinate names and convert them to
dimension labels internally. The data stays lazy — it is a dask array — so
nothing is read until you compute.

Writing back out
----------------

.. code-block:: python

    myfits.write_to_fits(
        "out.fits",
        coord_names=["STOKES", "FREQ", "DEC", "RA"],   # python ordering
        chunks={"RA": 64, "DEC": 64},
    )

``coord_names`` is given in python order and determines the output ``NAXISn``
assignment — the list above produces ``RA`` as ``NAXIS1`` and ``STOKES`` as
``NAXIS4``. Headers are rebuilt from the coordinates, so stale keywords from
dropped axes do not survive.

``write_to_fits`` will not replace an existing file unless you say so:

.. code-block:: python

    myfits.write_to_fits("out.fits")                   # raises if out.fits exists
    myfits.write_to_fits("out.fits", overwrite=True)   # replaces it

The write lands through a temporary file in the same directory and is renamed
into place, so writing back over the file you opened is safe, and a write that
fails part way leaves the previous contents alone. See :doc:`security`.

From the command line
---------------------

The same operations are available as subcommands:

.. code-block:: console

    $ fitstoolz --help
    $ fitstoolz header image.fits --show
    $ fitstoolz stats image.fits --show
    $ fitstoolz slice image.fits --axis FREQ,0,64 --outfile cube-sub.fits
    $ fitstoolz stack chan0.fits --axis FREQ --extra-files chan1.fits --stacked-fits cube.fits
    $ fitstoolz add-axis image.fits --ctype STOKES --index 4 --outfile with-stokes.fits

Apps that write take either ``--outfile PATH`` or ``--replace`` (edit the input
in place). Give neither and the command fails rather than guessing a filename.

See :doc:`cli` for the full generated reference.

Opening files in your own code
------------------------------

If you need an ``HDUList`` directly, use :func:`fitstoolz.utils.open_fits`
rather than ``astropy.io.fits.open``:

.. code-block:: python

    from fitstoolz.utils import open_fits

    with open_fits("image.fits") as hdul:
        ...

``astropy.io.fits.open`` will *fetch* a name that looks like a URL.
``open_fits`` requires a path that exists locally, which is what keeps a
filename argument from becoming a network request — see :doc:`security`.
