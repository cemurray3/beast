import os

import numpy as np
from astropy.tests.helper import remote_data
from astropy.table import Table
from astropy.io import fits
import tables

from beast.tools import create_background_density_map

@remote_data
def split_and_check(grid_fname, num_subgrids):

    gst_file = download_rename("b15_4band_det_27_A.fits")

    # not currently doing background density bins
    # use_bg_info = True

    ref_filter = ["F475W"]

    background_args = types.SimpleNamespace(
        subcommand="background",
        catfile=gst_file,
        pixsize=5,
        npix=None,
        reference=im_file,
        mask_radius=10,
        ann_width=20,
        cat_filter=[ref_filter, "90"],
    )
    create_background_density_map.main_make_map(background_args)
    # else:
    #     # - pixel size of 10 arcsec
    #     # - use ref_filter[b] between vega mags of 17 and peak_mags[ref_filter[b]]-0.5
    #     sourceden_args = types.SimpleNamespace(
    #         subcommand="sourceden",
    #         catfile=gst_file,
    #         pixsize=5,
    #         npix=None,
    #         mag_name=ref_filter + "_VEGA",
    #         mag_cut=[15, peak_mags[ref_filter - 0.5]],
    #         flag_name=flag_filter[b]+'_FLAG',
    #     )
    #     create_background_density_map.main_make_map(sourceden_args)
