import os.path
import shutil
import tempfile
import warnings

import numpy as np
from astropy.io import fits
from astropy.utils.data import download_file
from astropy.wcs import WCS

TESTDIR = os.path.abspath(os.path.dirname(__file__))


class InitTest:
    def __init__(self):
        self.test_files = []

    def astropy_example_image(self, fname=None):
        fname = fname or "HorseHead.fits"
        image_file = download_file(f"http://data.astropy.org/tutorials/FITS-images/{fname}")
        self.test_files.append(image_file)
        return image_file

    def random_named_file(self, suffix: str = None):
        if not hasattr(self, "test_files"):
            self.test_files = []

        file_obj = tempfile.NamedTemporaryFile(suffix=suffix, dir=TESTDIR, delete=False)
        name = file_obj.name
        file_obj.close()

        self.test_files.append(name)
        return name

    def random_named_directory(self, suffix: str = None):
        if not hasattr(self, "test_files"):
            self.test_files = []

        name = tempfile.mkdtemp(suffix=suffix, dir=TESTDIR)

        self.test_files.append(name)
        return name

    def example_fits_file(self):
        pix_size = 5 / 3600
        npix = 128
        dfreq = 1e6
        freq0 = 1.4e9
        nchan = 2
        wcs = WCS(naxis=3)
        wcs.wcs.ctype = ["RA---SIN", "DEC--SIN", "FREQ"]
        wcs.wcs.cdelt = np.array([-pix_size, pix_size, dfreq])
        wcs.wcs.crpix = [npix / 2, npix / 2, 1]
        wcs.wcs.crval = [2.0, -30, freq0]
        wcs.wcs.cunit = ["deg", "deg", "Hz"]

        # make header
        header = wcs.to_header()

        # make image
        image = np.random.randn(nchan, npix, npix).astype(np.float32)
        # put a point source at the center
        # write to FITS file
        hdu = fits.PrimaryHDU(image, header=header)
        hdul = fits.HDUList([hdu])
        test_filename = self.random_named_file(".fits")
        hdul.writeto(test_filename, overwrite=True)
        hdul.close()

        return test_filename

    def __del__(self):
        for path in getattr(self, "test_files", []):
            if os.path.exists(path):
                if os.path.isfile(path):
                    try:
                        os.remove(path)
                    except OSError as e:
                        # A failed cleanup leaks a temp file but must not fail
                        # the run; warn so pytest surfaces it in the summary.
                        warnings.warn(f"Error deleting file '{path}': {e}", stacklevel=2)
                elif os.path.isdir(path):
                    try:
                        shutil.rmtree(path)
                    except OSError as e:
                        warnings.warn(f"Error deleting directory '{path}': {e}", stacklevel=2)
