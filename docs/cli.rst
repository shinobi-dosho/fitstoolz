.. _cli:

Command-line reference
======================

The ``fitstoolz`` command groups a handful of small FITS operations. Every
subcommand takes the input file as a positional argument. Commands that write
require an explicit output path, a prefix, or ``--replace``.

The options below are generated from each app's typed signature — the same
typed function that defines the optional step when it is called from a
`stimela-ninja <https://github.com/shinobi-dosho/stimela-ninja>`_ recipe. There
is one schema. The native command line needs no Ninja installation; install
``fitstoolz[ninja]`` for pipeline adapters.

.. click:: fitstoolz.apps.main:cli
   :prog: fitstoolz
   :nested: full

Output paths
------------

``fitstoolz.apps.outfits_name`` resolves the destination for the apps that write
a modified copy:

* ``--outfile PATH`` — write there.
* ``--replace`` — write back over the input file.
* neither — the command raises. There is deliberately no default output name.

``stack`` writes to its required ``--stacked-fits`` instead. ``unstack`` requires
``--axis NAME --output-prefix PATH`` and writes one file per zero-based pixel
along that named axis, retaining the axis at length one. For example,
``--output-prefix products/channel`` writes ``products/channel-0000.fits``,
``products/channel-0001.fits``, and so on, in pixel order. Indices use at least
four digits, widening for longer axes. A trailing ``.fits`` on the prefix is
stripped. The parent directory must already exist.

Existing files with these generated names are overwritten. Every destination
is checked against the input before the first write; paths, symlinks, and hard
links to the input are rejected. Each file is written atomically, but the set
is not a transaction: a later failure can leave earlier outputs in place.
The recipe step returns the ordered paths as ``unstacked_fits: list[str]``.
``stats`` writes nothing at all.

The apps pass ``overwrite=True`` down to :meth:`~fitstoolz.reader.FitsData.write_to_fits`,
so a destination you name on the command line is a destination the app will
replace. The library default is the other way round — see :doc:`security`.
