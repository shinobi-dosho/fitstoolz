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

Each app module exposes a native ``command`` and a plain ``runit(opts)``.
With ``fitstoolz[ninja]`` installed, requesting ``step`` or the existing
named export (``add_axis``, ``remove_axis``, ``stack``, ``unstack``, ``slice_``,
``stats`` or ``header``) loads the same cached ``StepRef``. The native command
and adapter derive their schema from one typed function. See
:doc:`../cli` for the generated option reference.

.. automodule:: fitstoolz.apps
   :members:
   :undoc-members:
   :show-inheritance:
