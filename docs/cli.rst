.. _cli:

Command-line reference
======================

The ``fitstoolz`` command groups a handful of small FITS operations. Every
subcommand takes the input file as a positional argument, and every subcommand
that writes takes either ``--outfile`` or ``--replace``.

The options below are generated from each app's typed signature — the same
pydantic model that defines the step when it is called from a
`stimela-ninja <https://github.com/shinobi-dosho/stimela-ninja>`_ recipe. There
is one schema, so the command line and the pipeline step cannot drift apart.

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

``stack`` writes to its required ``--stacked-fits`` instead, and ``stats``
writes nothing at all.

All writes use ``overwrite=True``; see :doc:`security`.
