import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import dask.array as da
import numpy as np
import xarray as xr
from astropy import units
from astropy.coordinates import SpectralCoord
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS
from dask.array.core import normalize_chunks

from fitstoolz.utils import contiguous_chunks, get_beam_table, open_fits

log = logging.getLogger(__name__)


def read_block(fname, hdu_index=0, block_info=None):
    """Read a single dask block straight off disk.

    Opening the file per block rather than reusing the ``FitsData`` handle is
    deliberate, for two reasons. ``HDU.section`` reads through the HDU's own file
    object, so blocks running under the threaded scheduler would otherwise be
    sharing one seek position. And a graph that carries its own filename can be
    computed after the ``FitsData`` it came from has been closed, which is what
    lets ``get_xds`` results outlive a ``with`` block.

    Args:
        fname (str|Path): FITS file to read from.
        hdu_index (int): HDU to read.
        block_info: Supplied by ``dask.array.map_blocks``; says which corner of
            the array this call is responsible for.

    Returns:
        numpy.ndarray: The block's data.
    """
    slices = tuple(slice(start, stop) for start, stop in block_info[None]["array-location"])
    # memmap=False: `section` reads only the bytes asked for, so mapping the
    # whole file into every worker's address space buys nothing.
    with open_fits(fname, memmap=False) as hdulist:
        return np.asarray(hdulist[hdu_index].section[slices])


def lazy_data(fname, hdu, hdu_index=0):
    """An HDU's data as a dask array that has not been read yet.

    ``da.asarray(hdu.data)`` -- which this replaced at both call sites -- pulls
    the whole array into memory the moment it is called, whatever it is chunked
    to afterwards, which caps the package at data that fits in RAM. The blocks
    below read their own slice on demand instead, so building one costs a header
    parse and the graph stays a few kilobytes however large the array is.

    Note that ``hdu`` is consulted for its shape and dtype only; the blocks
    reopen ``fname`` when they run, so the array outlives the handle.

    Args:
        fname (str|Path): File the blocks reopen to do their reads.
        hdu: Open HDU, for its shape and dtype.
        hdu_index (int): Index of that HDU within the file.

    Returns:
        dask.array.Array: Lazy view of the HDU's data.
    """
    shape = tuple(hdu.shape)
    if not shape:
        # A header-only HDU has nothing to chunk. Leave it to astropy, and to
        # the caller, to say so.
        return da.asarray(hdu.data)

    # Ask the file for one element rather than deriving the dtype from BITPIX:
    # `section` applies BSCALE/BZERO, so a scaled integer image reports the
    # float dtype its blocks will really carry.
    dtype = hdu.section[tuple(slice(0, 1) for _ in shape)].dtype

    return da.map_blocks(
        read_block,
        fname=fname,
        hdu_index=hdu_index,
        dtype=dtype,
        chunks=normalize_chunks(contiguous_chunks(shape, dtype), shape=shape, dtype=dtype),
        meta=np.empty((), dtype=dtype),
    )


def to_unit(value, from_unit, to_unit_):
    """Convert a scalar between two FITS unit strings, passing it through if it cannot.

    Unitless axes (STOKES) and headers with no CUNIT are ordinary here, not
    errors, so anything that does not describe a convertible pair is returned
    unchanged rather than raised on.
    """
    if not from_unit or not to_unit_ or from_unit == to_unit_:
        return value
    try:
        return float((value * units.Unit(from_unit)).to(units.Unit(to_unit_)).value)
    except (ValueError, TypeError, units.UnitConversionError):
        return value


class FitsData:
    def __init__(self, fname: str, memmap: bool = True, hdu: int = 0):
        self.fname = Path(fname)
        self.hdulist = open_fits(self.fname, memmap=memmap)
        # Which HDU carries the image. Everything downstream reads through
        # `phdu` or `hdu_index`, so a file whose cube is not the primary HDU
        # -- an MEF, or one with a compressed image in an extension -- is
        # addressed the same way as one where it is.
        self.hdu_index = hdu
        self.phdu = self.hdulist[hdu]
        self.header = self.phdu.header
        self.wcs = WCS(self.header)
        self.dim_info = self.wcs.get_axis_types()[::-1]
        self.coord_names = self.wcs.axis_type_names[::-1]
        self.coords = xr.Coordinates()
        self.open_arrays = []
        self.spectral_coord = None
        self.data = lazy_data(self.fname, self.phdu, hdu_index=hdu)
        self.data_units = self.header.get("BUNIT", "Jy").strip()

        # astropy drops trailing axes with no NAXISn from array_shape, so an
        # over-declared WCSAXES slips past a shape comparison alone and only
        # surfaces later as an IndexError against coord_names.
        if self.wcs.naxis != self.data.ndim or self.dshape != self.wcs.array_shape:
            raise RuntimeError(
                f"Input FITS file WCS information does not match Image data: "
                f"WCS describes {self.wcs.naxis} axes {self.wcs.array_shape}, data has "
                f"{self.data.ndim} axes {self.dshape}"
            )

        self.__register_dimensions()
        self.__register_beam_table()

    def coord_index(self, name: str) -> int:
        """
        Returns index of given axis

        Args:
            name (str): Coordinate/axis name

        Returns:
        int : coordinate index
        """
        return self.coord_names.index(name)

    @property
    def nchan(self):
        if self.spectral_coord is None:
            return 0
        return self.coords[self.spectral_coord].size

    @property
    def ndim(self):
        return self.data.ndim

    @property
    def dims(self):
        return [self.coords[name].dim for name in self.coord_names]

    @property
    def dshape(self):
        return self.data.shape

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

    def set_coord_attrs(self, name: str, dim: str):
        """
        Add FITS pixel meta data to this instances coords attribute (xarray.Coordinates)

        Args:
            name (str): Name (or label) of coordinate to set
        """
        idx = self.coord_index(name)
        self.coords[name].attrs = {
            "name": name,
            "pixel_size": self.header[f"CDELT{self.ndim - idx}"],
            "dim": dim,
            "ref_pixel": int(self.header[f"CRPIX{self.ndim - idx}"]) - 1,  # FITS indexing is 1-based
            "units": self.wcs.world_axis_units[::-1][idx],
            "size": self.dshape[idx],
        }

    def __register_dimensions(self):
        """
        Register (or set) FITS data coordinate and dimension data from the FITS header
        (including WCS information)

        """
        # Ensure fresh start
        self.coords = xr.Coordinates()
        names = self.coord_names
        celestial_already_set = False
        for idx, coord in enumerate(names):
            diminfo = self.dim_info[idx]
            dim = diminfo["coordinate_type"]

            if dim == "celestial":
                if celestial_already_set:
                    continue
                # these only need to be set once
                self.set_celestial_dimensions()
                celestial_already_set = True
                continue
            elif dim == "spectral":
                self.set_spectral_dimension(coord)
                continue
            elif dim == "stokes":
                self.set_stokes_dimensions(coord)
                continue

            # Anything left is an axis astropy could not classify (a linear or
            # blank CTYPE): coordinate_type is None and there is no sub-WCS to
            # evaluate. Fall back to pixel indices, naming the dimension after
            # the axis itself.
            dim = (dim or coord or f"axis{idx}").lower()
            self.coords[coord] = (dim,), da.arange(self.dshape[idx])
            self.set_coord_attrs(coord, dim)

    def set_stokes_dimensions(self, coord_name: str):
        """
        Args:
            coord_name (str): _description_
        """

        idx = self.coord_index(coord_name)
        crval = int(self.header.get(f"CRVAL{self.ndim - idx}", 1))
        crpix = int(self.header.get(f"CRPIX{self.ndim - idx}", 1))
        cdelt = int(self.header.get(f"CDELT{self.ndim - idx}", 1))
        naxis = int(self.header.get(f"NAXIS{self.ndim - idx}"))
        size = cdelt * naxis
        grid = np.arange(0, size, cdelt)
        shift = grid[crpix - 1] + crval
        grid += shift

        self.coords[coord_name] = ("stokes",), grid
        self.set_coord_attrs(coord_name, "stokes")

    def set_spectral_dimension(self, coord_name, rest_freq=None):
        idx = self.coord_index(coord_name)
        dimsize = self.dshape[idx]

        dimgrid = self.wcs.spectral.array_index_to_world_values(da.arange(dimsize))
        self.coords[coord_name] = ("spectral",), dimgrid
        self.set_coord_attrs(coord_name, "spectral")
        self.spectral_coord = coord_name
        self.spectral_refpix = self.coords[coord_name].ref_pixel
        self.spectral_units = self.wcs.spectral.world_axis_units[0]
        self.spectral_restfreq = rest_freq or self.header.get("RESTFRQ", None)

    def set_celestial_dimensions(self):
        """
        Set celestial coordinate grids from the FITS WCS information.

        The sky grid is not separable under a projection: the longitude of a
        pixel depends on its latitude and vice versa. A one-dimensional
        coordinate array is therefore only meaningful along a principal axis,
        so each axis is sampled through the reference pixel of the other by
        evaluating the WCS. Stepping a grid by ``CDELT`` instead would be wrong
        by ``1/cos(dec)`` for the longitude axis, since ``CDELT`` is an angle on
        the sky rather than a coordinate increment.
        """
        ra_idx = dec_idx = None
        for idx, diminfo in enumerate(self.dim_info):
            dim = diminfo["coordinate_type"]
            dim_number = diminfo["number"]
            if dim == "celestial":
                if dim_number == 0:
                    ra_idx = idx
                elif dim_number == 1:
                    dec_idx = idx
                else:
                    raise ValueError(f"Unkown celestial dimension in WCS: {dim_number}")

        if ra_idx is None or dec_idx is None:
            raise RuntimeError("FITS WCS does not define a pair of celestial axes")

        ra_dim = self.coord_names[ra_idx]
        dec_dim = self.coord_names[dec_idx]
        ra_dimsize = self.dshape[ra_idx]
        dec_dimsize = self.dshape[dec_idx]

        celestial = self.wcs.celestial
        # Indices of the longitude and latitude axes within the celestial WCS,
        # which need not be in (longitude, latitude) order.
        lng, lat = celestial.wcs.lng, celestial.wcs.lat
        lng_refpix = celestial.wcs.crpix[lng] - 1  # CRPIX is 1-based
        lat_refpix = celestial.wcs.crpix[lat] - 1

        ra_pixels = np.empty((ra_dimsize, 2))
        ra_pixels[:, lng] = np.arange(ra_dimsize)
        ra_pixels[:, lat] = lat_refpix
        ra_grid = celestial.wcs_pix2world(ra_pixels, 0)[:, lng]

        dec_pixels = np.empty((dec_dimsize, 2))
        dec_pixels[:, lng] = lng_refpix
        dec_pixels[:, lat] = np.arange(dec_dimsize)
        dec_grid = celestial.wcs_pix2world(dec_pixels, 0)[:, lat]

        # Keep the longitude monotonic across the 0/360 wrap.
        if celestial.wcs.cunit[lng] == "deg":
            ra_grid = np.unwrap(ra_grid, period=360.0)

        self.coords[ra_dim] = ("celestial.ra",), ra_grid
        self.set_coord_attrs(ra_dim, "celestial.ra")

        self.coords[dec_dim] = ("celestial.dec",), dec_grid
        self.set_coord_attrs(dec_dim, "celestial.dec")

    def get_freq_from_vrad(self, rest_freq_Hz=None):
        """
        Convert radio velocity coordinates to frequencies

        Returns:
            astropy.SpectralCoord: Astropy SpectralCoord instance
        """
        rest_freq_Hz = rest_freq_Hz or self.spectral_restfreq
        return (
            SpectralCoord(self.coords["VRAD"], unit=units.meter / units.second)
            .to(units.Hz, doppler_rest=rest_freq_Hz * units.Hz, doppler_convention="radio")
            .value
        )

    def get_freq_from_vopt(self, rest_freq_Hz=None):
        """
        Convert radio velocity coordinates to frequencies

        Returns:
            astropy.SpectralCoord: Astropy SpectralCoord instance
        """
        rest_freq_Hz = rest_freq_Hz or self.spectral_restfreq
        return (
            SpectralCoord(self.coords["VOPT"], unit=units.meter / units.second)
            .to(units.Hz, doppler_rest=rest_freq_Hz * units.Hz, doppler_convention="optical")
            .value
        )

    def add_axis(self, name: str, idx: int, crval: float, cdelt: float, crpix: int, cunit: str):
        """Add a new axis to FITS data

        Args:
            name (str): Name of new axis. e.g, STOKES, RA, DEC
            idx (int): FITS-style index where new axis is added (1-based, NAXISn convention)
            crval (float): Value at reference pixel
            cdelt (float): Pixel width
            crpix (int): Reference pixel
            cunit (str): Units (astropy naming convention)

        Raises:
            RuntimeError: Dimensions not matching after axis was added
        """
        idx_py = self.ndim - idx + 1
        slc = [slice(None)] * (self.ndim + 1)
        slc[idx_py] = da.newaxis
        self.data = self.data[tuple(slc)]

        for n in range(self.ndim, idx, -1):
            for key in ("NAXIS", "CTYPE", "CRPIX", "CRVAL", "CDELT", "CUNIT"):
                old_val = self.header.pop(f"{key}{n - 1}", None)
                if old_val is not None:
                    self.header[f"{key}{n}"] = old_val

        self.header[f"NAXIS{idx}"] = 1
        self.header[f"CTYPE{idx}"] = name
        self.header[f"CRPIX{idx}"] = crpix + 1
        self.header[f"CRVAL{idx}"] = crval
        self.header[f"CDELT{idx}"] = cdelt
        self.header[f"CUNIT{idx}"] = cunit
        self.header["NAXIS"] = self.ndim

        self.wcs = WCS(self.header)
        self.dim_info = self.wcs.get_axis_types()[::-1]
        self.coord_names = self.wcs.axis_type_names[::-1]
        self.__register_dimensions()

        if len(self.coord_names) != self.ndim:
            raise RuntimeError(f"New axis '{name}' could not be added")

    def expand_along_axis(self, name: str, data: np.ndarray, beams: Table = None):
        """
        Expand data along the given dimension.

        Args:
            name (str): Name of expansion coordinate
            data (np.ndarray): Data slice to add along the axis. Number of dimensions
                must be equal or one less than the current data
        """
        idx = self.coord_index(name)
        dim = self.coords[name].dim

        if len(data.shape) == self.ndim - 1:
            slc = [slice(None)] * self.ndim
            slc[idx] = da.newaxis
            data = data[tuple(slc)]
        self.data = da.concatenate((self.data, data), axis=idx)

        old_grid = self.__coord_values(name)
        in_ndim = data.shape[idx]

        # Step off the coordinate grid, not `pixel_size`. CDELT is in the axis'
        # header units while `coords` is in the units astropy reports -- SI for a
        # spectral axis -- so on a cube whose CUNIT is not already SI the two
        # differ by exactly that factor, and the appended channels land on top of
        # each other instead of continuing the band.
        if old_grid.size > 1:
            step = float(old_grid[1] - old_grid[0])
        else:
            step = float(self.coords[name].pixel_size)

        # Count out the new values rather than `arange(start, stop, step)`. The
        # arange form derives its length from the endpoints, and floating point
        # puts that one out often enough to leave the grid and the data
        # disagreeing about how many channels there are.
        new_grid = np.concatenate((old_grid, old_grid[-1] + step * np.arange(1, in_ndim + 1)))

        new_coord = (dim,), new_grid
        coords = xr.Coordinates()
        for coord in self.coord_names:
            if coord == name:
                coords[coord] = new_coord
            else:
                coords[coord] = self.coords[coord]
        self.coords = coords
        self.set_coord_attrs(name, dim)

        self.__extend_beam_table(beams)

    def __extend_beam_table(self, beams):
        """Append an incoming file's beams, or give up on the table entirely.

        A per-channel beam table only means anything if it has a row per channel.
        The moment one file in a stack carries beams and another does not, no
        honest table describes the result -- and since ``write_to_fits`` emits
        the table, a short one would be written out as though it did. Drop it and
        say so.

        This used to append blindly, which crashed with an ``AttributeError``
        when the first file had no beams, and silently produced a table shorter
        than the cube when a later one did not.
        """
        incoming = beams if isinstance(beams, Table) else None

        if self.beam_table is None and incoming is None:
            return

        if self.beam_table is None or incoming is None:
            if self.beam_table is not None:
                log.warning(
                    "Dropping the beam table: not every file being stacked has one, "
                    "so no per-channel table describes the result."
                )
            self.beam_table = None
            self.beam_table_extname = None
            return

        for row in incoming:
            self.beam_table.add_row(row)

    def expand_along_axis_from_files(self, name, files: List[Path]):
        """Stack further files onto this one along ``name``.

        Each file is read at the same HDU index this ``FitsData`` was opened at,
        on the grounds that a stack of like files is like all the way down.
        """
        idx = self.coord_index(name)
        for fname in files:
            with open_fits(fname, memmap=True) as hdul:
                hdu = hdul[self.hdu_index]
                # `shape`, not `data.ndim`: the point of the lazy read below is
                # not to touch the array, and `.data` on a scaled image would.
                data = lazy_data(fname, hdu, hdu_index=self.hdu_index)
                if self.ndim != len(hdu.shape):
                    slc = [slice(None)] * self.ndim
                    slc[idx] = da.newaxis
                    data = data[tuple(slc)]
                beam_table = get_beam_table(fname, hdu=self.hdu_index)
            self.expand_along_axis(name, data, beam_table)

    def __register_beam_table(self):
        beam_table = get_beam_table(self.fname, hdu=self.hdu_index)
        if beam_table is False:
            self.beam_table = None
            self.beam_table_extname = None
            return

        # Set only when the beams arrived as their own extension. Beams that came
        # from BMAJ/BMIN/BPA keywords are already carried by the header copy on
        # the way out, so writing a table for them would add an extension the
        # input never had -- and, for a single beam expanded over frequency
        # below, would promote this package's scaling model to recorded data.
        self.beam_table_extname = beam_table.meta.get("EXTNAME")

        nbeams = len(beam_table)

        if nbeams == 1 and self.spectral_coord and self.coords[self.spectral_coord].size > 1:
            if self.spectral_coord == "VRAD":
                freqs = self.get_freq_from_vrad()
            elif self.spectral_coord == "VOPT":
                freqs = self.get_freq_from_vopt()
            else:
                freqs = self.coords["FREQ"].data
            new_table = {}
            for col in beam_table.colnames:
                col_data = np.zeros(self.nchan, dtype=beam_table[col].dtype)
                for chan in range(self.nchan):
                    scale_factor = freqs[self.spectral_refpix] / freqs[chan]
                    if col.lower() in ["bmaj", "bmin"]:
                        col_data[chan] = beam_table[col][0] * scale_factor
                    elif col.lower() == "chan":
                        col_data[chan] = chan
                    else:
                        col_data[chan] = beam_table[col][0]
                col_unit = getattr(beam_table[col], "unit", None) or 1
                new_table[col] = col_data * col_unit
            # Carry the source metadata (EXTNAME and friends) across the
            # expansion; a bare Table() would drop it and lose the provenance.
            beam_table = Table(new_table, meta=beam_table.meta)

        self.beam_table = beam_table

    def __output_beam_hdu(self, coord_names, data_slice):
        """The beam extension to write beside the data, if there is one to write.

        Returns None unless the beams came from an extension of their own --
        beams read out of BMAJ/BMIN/BPA keywords ride along in the header copy
        already, and re-emitting them as a table would change what the file
        claims to record.

        Rows follow the data: a spectral ``data_slice`` cuts the table to the
        channels being written, and a ``CHAN`` column is renumbered against the
        output rather than left pointing at the input's channels.

        Args:
            coord_names (list): Output coordinate order, python convention.
            data_slice (list): Per-axis slices being written.

        Returns:
            astropy.io.fits.BinTableHDU|None
        """
        if self.beam_table is None or self.beam_table_extname is None:
            return None

        beams = self.beam_table
        spectral = self.spectral_coord

        if spectral is not None and spectral in coord_names and data_slice:
            idx = self.coord_index(spectral)
            # Only a per-channel table tracks the spectral axis; a single beam
            # describes the whole cube however it is sliced.
            if len(beams) == self.dshape[idx] and isinstance(data_slice[idx], slice):
                beams = beams[data_slice[idx]]

        if beams is not self.beam_table:
            beams = beams.copy()
            for col in beams.colnames:
                if col.upper() == "CHAN":
                    beams[col] = np.arange(len(beams), dtype=beams[col].dtype)

        if "NCHAN" in beams.meta:
            beams.meta["NCHAN"] = len(beams)

        return fits.BinTableHDU(beams, name=self.beam_table_extname)

    def regrid_axis(self, name: str, values, data, cunit: str = None):
        """Put the array on a new grid along one axis, changing its length.

        ``coords`` is an ``xarray.Coordinates``, so a coordinate of a different
        length cannot simply be assigned to it -- xarray aligns, and raises. This
        is the supported way to say "same cube, resampled": it replaces the data
        and the grid together, so the two are never briefly inconsistent, then
        rebuilds the header and every coordinate from the new WCS.

        A FITS axis is linear in ``CRVAL``/``CDELT``, so ``values`` must be
        evenly spaced; anything else cannot be written to a header and is
        rejected rather than silently approximated.

        If the regridded axis is the spectral one and the beams are per-channel,
        the beam table is interpolated onto the new grid -- see
        :meth:`__regrid_beam_table`.

        Args:
            name (str): Coordinate to regrid, e.g. ``'FREQ'``.
            values (array): New coordinate values, in the axis' header units --
                the ``CUNIT`` it has now, or ``cunit`` if that is given. Note
                these are not necessarily the units ``coords`` reports back:
                astropy normalises a spectral coordinate to SI regardless.
            data (array): The array on that new grid. Must match the current
                shape on every other axis, and ``len(values)`` on this one.
            cunit (str, optional): New units for the axis, if they changed.

        Raises:
            ValueError: ``data`` does not match ``values`` or the other axes, or
                ``values`` is not evenly spaced.
        """
        idx = self.coord_index(name)
        values = np.asarray(values, dtype=float)

        if data.ndim != self.ndim:
            raise ValueError(f"New data has {data.ndim} axes, but this cube has {self.ndim}")
        if data.shape[idx] != values.size:
            raise ValueError(
                f"New data has {data.shape[idx]} elements along '{name}', but {values.size} coordinates were given"
            )
        for axis, (was, now) in enumerate(zip(self.dshape, data.shape)):
            if axis != idx and was != now:
                raise ValueError(f"regrid_axis only changes '{name}'; axis {axis} went from {was} to {now}")

        fits_axis = self.ndim - idx
        if values.size > 1:
            steps = np.diff(values)
            cdelt = float(steps.mean())
            if not np.allclose(steps, cdelt, rtol=1e-6, atol=0):
                raise ValueError(
                    f"'{name}' values are not evenly spaced, so they cannot be written as a FITS CRVAL/CDELT axis"
                )
        else:
            cdelt = float(self.header.get(f"CDELT{fits_axis}", 1.0))

        old_grid = self.__coord_values(name)

        self.header[f"NAXIS{fits_axis}"] = int(values.size)
        self.header[f"CRPIX{fits_axis}"] = 1
        self.header[f"CRVAL{fits_axis}"] = float(values[0])
        self.header[f"CDELT{fits_axis}"] = cdelt
        if cunit is not None:
            self.header[f"CUNIT{fits_axis}"] = cunit

        self.data = data
        self.wcs = WCS(self.header)
        self.dim_info = self.wcs.get_axis_types()[::-1]
        self.coord_names = self.wcs.axis_type_names[::-1]
        self.__register_dimensions()

        if name == self.spectral_coord:
            # Both grids read back off `coords`, never from `values`. astropy
            # reports a spectral coordinate in SI whatever CUNIT says, so
            # interpolating the header-unit `values` against the SI `old_grid`
            # would be out by a factor of CUNIT on any cube not already in Hz.
            self.__regrid_beam_table(old_grid, self.__coord_values(name))

    def __coord_values(self, name):
        """A coordinate's grid as a flat float array, in the units astropy reports."""
        return np.asarray(da.compute(self.coords[name].data)[0], dtype=float).ravel()

    def __regrid_beam_table(self, old_grid, new_grid):
        """Carry a per-channel beam table onto a new spectral grid.

        The beams are a smooth function of frequency, so they are interpolated
        rather than dropped -- ``__register_beam_table`` already models a single
        beam's frequency dependence, and interpolating measured per-channel
        beams is the more faithful of the two. A table that does not have one row
        per input channel describes the cube as a whole and is left alone.
        """
        beams = self.beam_table
        if beams is None or len(beams) != old_grid.size or old_grid.size < 2:
            return

        # np.interp needs an increasing sample grid; a spectral axis with a
        # negative CDELT runs the other way.
        order = np.argsort(old_grid)
        samples = old_grid[order]

        columns = {}
        for col in beams.colnames:
            column = np.asarray(beams[col])
            if col.upper() == "CHAN":
                values = np.arange(new_grid.size, dtype=column.dtype)
            elif np.issubdtype(column.dtype, np.floating):
                values = np.interp(new_grid, samples, column[order])
            else:
                # Labels rather than measurements (POL): take the nearest input
                # channel instead of averaging between two of them.
                nearest = np.abs(new_grid[:, None] - old_grid[None, :]).argmin(axis=1)
                values = column[nearest]
            unit = getattr(beams[col], "unit", None)
            columns[col] = values * unit if unit is not None else values

        meta = dict(beams.meta)
        if "NCHAN" in meta:
            meta["NCHAN"] = int(new_grid.size)
        self.beam_table = Table(columns, meta=meta)

    def get_data(self, data_slice=None) -> np.ndarray:
        if data_slice:
            data = self.phdu.section[tuple(data_slice)]
        else:
            data = self.phdu.data
        self.open_arrays.append(data)

        return self.open_arrays[-1]

    def get_xds(self, data_slice=[], transpose=[], chunks={"RA": 64, "DEC": 64}, **kwargs):
        dim_chunks = {}
        # swap coords for dims in chunks
        for key, val in chunks.items():
            if key in self.coord_names:
                key = self.coords[key].attrs["dim"]
            dim_chunks[key] = val

        if len(transpose) == 0:
            transpose = self.dims

        # swap coords for dims in transpose
        dim_transpose = []
        for key in transpose:
            if key in self.coord_names:
                key = self.coords[key].attrs["dim"]
            dim_transpose.append(key)

        if len(data_slice) == 0:
            data_slice = [slice(None)] * self.ndim

        data = da.asarray(self.data[tuple(data_slice)])

        # Create a new coordinate instance to ensure alignment with the data.
        # Each coordinate must be cut by the same slice as its data axis,
        # otherwise xarray rejects the mismatched dimension lengths.
        coords = xr.Coordinates()
        for idx, coord in enumerate(self.coord_names):
            coord_dim = self.coords[coord].attrs["dim"]
            if coord_dim in dim_transpose:
                coords[coord] = self.coords[coord][data_slice[idx]]

        xds = xr.DataArray(
            data,
            coords=coords,
            attrs={
                "header": dict(self.header.items()),
            },
            **kwargs,
        ).transpose(*dim_transpose)

        return xds.chunk(dim_chunks)

    def build_chunks(self, ra_chunks=None, dec_chunks=None, spectral_chunks=None):
        chunks = {}
        if ra_chunks is not None:
            chunks["RA"] = ra_chunks
        if dec_chunks is not None:
            chunks["DEC"] = dec_chunks
        if spectral_chunks is not None and self.spectral_coord:
            chunks[self.spectral_coord] = spectral_chunks
        return chunks

    def write_to_fits(
        self,
        fname: Path,
        coord_names: list[str] = None,
        data_slice: List[Any] = None,
        chunks: Dict = None,
        overwrite: bool = False,
    ):
        """Write FitsData object into a FITS file

        Args:
            fname (Path): Name of FITS image to write
            coord_names (list[str]): Coordinates to include in the FITS image. The ordering is the Python convention.
                    For example, to get a FITS image with RA -> NAXIS1, DEC -> NAXIS2, FREQ -> NAXIS3, STOKES -> NAXIS4,
                    you need to give coord_names=['STOKES', 'FREQ', 'DEC', 'RA'].
            data_slice (slice): Tuple of sclices
            chunks (Dict|Mapping): How to chunk data when writing to disk
            overwrite (bool): Replace ``fname`` if it already exists. Defaults to
                    False -- this used to be hardcoded to True, which left a
                    caller no way to offer its own users a --no-overwrite.

        A beam table read from an extension of its own is written back beside the
        data, with its rows cut to whatever ``data_slice`` selects. Beams that
        came from ``BMAJ``/``BMIN``/``BPA`` header keywords need no extension --
        the header carries them already.

        Raises:
            FileExistsError: ``fname`` exists and ``overwrite`` is False.
        """

        coord_names = coord_names or self.coord_names
        data_slice = data_slice or []
        chunks = chunks or {}
        out_ndim = len(coord_names)

        header = fits.Header(self.header)
        header["NAXIS"] = out_ndim

        # The output is always a primary HDU, so the input's extension identity
        # must not ride along on it -- EXTNAME and friends are defined for
        # extensions. astropy drops XTENSION/PCOUNT/GCOUNT itself when it builds
        # the PrimaryHDU, but not these, so a cube read from an extension came
        # back out as a primary HDU still claiming to be called 'SCI'.
        for keyword in ("EXTNAME", "EXTVER", "EXTLEVEL"):
            header.pop(keyword, None)
        # Remove stale keywords from dimensions beyond out_ndim
        for n_extra in range(out_ndim + 1, self.ndim + 1):
            for key in ("NAXIS", "CTYPE", "CRPIX", "CRVAL", "CDELT", "CUNIT"):
                header.pop(f"{key}{n_extra}", None)

        for i, coord in enumerate(coord_names):
            idx = out_ndim - i
            orig_idx = self.coord_index(coord)

            orig_axis = self.ndim - orig_idx
            cdelt = self.coords[coord].pixel_size
            crpix = self.coords[coord].ref_pixel
            ctype = self.header.get(f"CTYPE{orig_axis}", coord)

            # CDELT is the input header's, so it is in the input's units, and
            # CUNIT has to say so. The coordinate grid is not in those units --
            # astropy reports a spectral axis in SI whatever CUNIT said -- so
            # CRVAL is converted back before it is written. Taking CUNIT from the
            # grid instead, as this did, described a cube in MHz as one in Hz
            # while leaving CDELT at its MHz value: a channel width a million
            # times too narrow, and no round trip.
            cunit = self.header.get(f"CUNIT{orig_axis}") or self.coords[coord].units
            crval = float(da.compute(self.coords[coord].data[crpix])[0])
            crval = to_unit(crval, self.coords[coord].units, cunit)

            header.update(
                {
                    f"CTYPE{idx}": ctype,
                    f"CDELT{idx}": cdelt,
                    f"CRPIX{idx}": crpix + 1,
                    f"CUNIT{idx}": cunit,
                    f"CRVAL{idx}": crval,
                }
            )
        fname = Path(fname)
        if fname.exists() and not overwrite:
            raise FileExistsError(f"Output FITS file '{fname}' already exists. Pass overwrite=True to replace it.")

        xds = self.get_xds(data_slice, coord_names, chunks)
        phdu = fits.PrimaryHDU(xds.data, header=header)

        hdulist = fits.HDUList([phdu])
        beam_hdu = self.__output_beam_hdu(coord_names, data_slice)
        if beam_hdu is not None:
            hdulist.append(beam_hdu)

        # Write beside the target and rename into place, rather than writing to
        # the target directly. `self.data` is read lazily from `self.fname`, so
        # writing in place -- which is exactly what the apps' `--replace` asks
        # for -- would otherwise truncate the file the blocks are still being
        # read from. The rename is atomic, so a write that dies part way also no
        # longer destroys whatever was there before.
        tmpname = fname.with_name(f".{fname.name}.fitstoolz-tmp")
        try:
            hdulist.writeto(tmpname, overwrite=True)
            os.replace(tmpname, fname)
        finally:
            if tmpname.exists():
                tmpname.unlink()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.hdulist.close()
        for data in self.open_arrays:
            del data

    def close(self):
        self.__exit__()
