---
name: Bug report
about: Report something that isn't working as expected
title: ""
labels: bug
assignees: ""
---

## Description

<!-- A clear description of the bug. -->

## Steps to reproduce

<!--
Minimal steps: the `fitstoolz` command line you ran, or a short snippet using
`FitsData`. If you can attach or describe the FITS file that triggers it, that
is the most useful thing in this report -- the header alone
(`fitstoolz header --show yourfile.fits`) is often enough.
-->

1.
2.

## FITS header

<!--
Output of `fitstoolz header --show yourfile.fits`, if the problem involves a
specific file. Paste as a code block; trim it if it's very long, but keep the
NAXIS/CTYPE/CRVAL/CRPIX/CDELT/CUNIT cards.
-->

## Expected behavior

<!-- What you expected to happen. -->

## Actual behavior

<!-- What actually happened, including any traceback (paste as a code block). -->

## Environment

- fitstoolz version (`pip show fitstoolz`):
- Python version:
- astropy / numpy / dask / xarray versions:
- OS:

## Additional context

<!-- Anything else that might help. -->
