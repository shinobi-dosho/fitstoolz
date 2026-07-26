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

from fitstoolz.utils import get_beam_table


class FitsData:
    def __init__(self, fname: str, memmap: bool = True):
        self.fname = Path(fname)
        if not self.fname.exists():
            raise FileNotFoundError(f"Input FITS file '{fname}' does not exist")

        self.hdulist = fits.open(self.fname, memmap=memmap)
        self.phdu = self.hdulist[0]
        self.header = self.phdu.header
        self.wcs = WCS(self.header)
        self.dim_info = self.wcs.get_axis_types()[::-1]
        self.coord_names = self.wcs.axis_type_names[::-1]
        self.coords = xr.Coordinates()
        self.open_arrays = []
        self.spectral_coord = None
        self.data = da.asarray(self.phdu.data)
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

        old_grid = da.compute(self.coords[name].data)[0]
        dpix = self.coords[name].pixel_size
        in_ndim = data.shape[idx]
        in_grid_start = old_grid[-1] + dpix
        in_grid_end = in_grid_start + dpix * in_ndim

        new_grid = da.concatenate(
            (
                old_grid,
                da.arange(in_grid_start, in_grid_end, dpix),
            ),
        )

        new_coord = (dim,), new_grid
        coords = xr.Coordinates()
        for coord in self.coord_names:
            if coord == name:
                coords[coord] = new_coord
            else:
                coords[coord] = self.coords[coord]
        self.coords = coords
        self.set_coord_attrs(name, dim)

        if beams:
            nbeams = len(beams)
            for chan in range(nbeams):
                self.beam_table.add_row(beams[chan])

    def expand_along_axis_from_files(self, name, files: List[Path]):
        idx = self.coord_index(name)
        for fname in files:
            with fits.open(fname, memmap=True) as hdul:
                slc = [slice(None)] * self.ndim
                if self.ndim != hdul[0].data.ndim:
                    slc[idx] = da.newaxis
                slc = tuple(slc)
                data = da.asarray(hdul[0].data[slc])
                beam_table = get_beam_table(fname)
            self.expand_along_axis(name, data, beam_table)

    def __register_beam_table(self):
        beam_table = get_beam_table(self.fname)
        if beam_table is False:
            self.beam_table = None
            return

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
            beam_table = Table(new_table)

        self.beam_table = beam_table

    def get_data(self, data_slice=None) -> np.ndarray:
        if data_slice:
            data = self.phdu.section[tuple(data_slice)]
        else:
            data = self.phdu.data
        self.open_arrays.append(data)

        return self.open_arrays[-1]

    def get_xds(self, data_slice=[], transpose=[], chunks=dict(RA=64, DEC=64), **kwargs):
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
        self, fname: Path, coord_names: list[str] = None, data_slice: List[Any] = None, chunks: Dict = None
    ):
        """Write FitsData object into a FITS file

        Args:
            fname (Path): Name of FITS image to write
            coord_names (list[str]): Coordinates to include in the FITS image. The ordering is the Python convention.
                    For example, to get a FITS image with RA -> NAXIS1, DEC -> NAXIS2, FREQ -> NAXIS3, STOKES -> NAXIS4,
                    you need to give coord_names=['STOKES', 'FREQ', 'DEC', 'RA'].
            data_slice (slice): Tuple of sclices
            chunks (Dict|Mapping): How to chunk data when writing to disk
        """

        coord_names = coord_names or self.coord_names
        data_slice = data_slice or []
        chunks = chunks or {}
        out_ndim = len(coord_names)

        header = fits.Header(self.header)
        header["NAXIS"] = out_ndim
        # Remove stale keywords from dimensions beyond out_ndim
        for n_extra in range(out_ndim + 1, self.ndim + 1):
            for key in ("NAXIS", "CTYPE", "CRPIX", "CRVAL", "CDELT", "CUNIT"):
                header.pop(f"{key}{n_extra}", None)

        for i, coord in enumerate(coord_names):
            idx = out_ndim - i
            orig_idx = self.coord_index(coord)

            cdelt = self.coords[coord].pixel_size
            crpix = self.coords[coord].ref_pixel
            cunit = self.coords[coord].units
            crval = da.compute(self.coords[coord].data[crpix])[0]
            ctype = self.header.get(f"CTYPE{self.ndim - orig_idx}", coord)

            header.update(
                {
                    f"CTYPE{idx}": ctype,
                    f"CDELT{idx}": cdelt,
                    f"CRPIX{idx}": crpix + 1,
                    f"CUNIT{idx}": cunit,
                    f"CRVAL{idx}": crval,
                }
            )
        xds = self.get_xds(data_slice, coord_names, chunks)
        phdu = fits.PrimaryHDU(xds.data, header=header)

        phdu.writeto(fname, overwrite=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.hdulist.close()
        for data in self.open_arrays:
            del data

    def close(self):
        self.__exit__()
