.. _api:

API reference
=============

.. currentmodule:: fitstoolz

Reader
------

.. automodule:: fitstoolz.reader
   :members:
   :undoc-members:
   :show-inheritance:

Utilities
---------

.. automodule:: fitstoolz.utils
   :members:
   :undoc-members:
   :show-inheritance:

Package
-------

.. automodule:: fitstoolz
   :members:
   :undoc-members:
   :show-inheritance:

Apps
----

Each app module exposes a ``step`` (the ``StepRef`` produced by
``@shinobi.pystep``) and a ``command`` (the ``click.Command`` built from it), so
the same function backs both the command line and a pipeline step. See
:doc:`../cli` for the generated option reference.

.. automodule:: fitstoolz.apps
   :members:
   :undoc-members:
   :show-inheritance:
