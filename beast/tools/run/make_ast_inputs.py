#!/usr/bin/env python

# system imports
import argparse
import os
import numpy as np
from astropy.table import Table

# BEAST imports
from beast.observationmodel.observations import Observations
from beast.observationmodel.ast.make_ast_input_list import (
    pick_models,
    pick_models_toothpick_style,
)
from beast.observationmodel.ast import make_ast_xy_list
from beast.tools import beast_settings


def make_ast_inputs(beast_settings_info, flux_bin_method=True):
    """
    Make the list of artificial stars to be run through the photometry pipeline

    Parameters
    ----------
    beast_settings_info : string or beast.tools.beast_settings.beast_settings instance
        if string: file name with beast settings
        if class: beast.tools.beast_settings.beast_settings instance

    flux_bin_method : boolean (default=True)
        If True, use the flux bin method to select SEDs.  If False, randomly
        select SEDs from the model grid.

    """

    # process beast settings info
    if isinstance(beast_settings_info, str):
        settings = beast_settings.beast_settings(beast_settings_info)
    elif isinstance(beast_settings_info, beast_settings.beast_settings):
        settings = beast_settings_info
    else:
        raise TypeError(
            "beast_settings_info must be string or beast.tools.beast_settings.beast_settings instance"
        )

    # read in the photometry catalog
    obsdata = Observations(
        settings.obsfile, settings.filters, obs_colnames=settings.obs_colnames
    )

    # --------------------
    # select SEDs
    # --------------------

    Nrealize = settings.ast_realization_per_model
    Nfilters = settings.ast_bands_above_maglimit

    # file names for stars and corresponding SED parameters
    outfile_seds = "./{0}/{0}_inputAST_seds.txt".format(settings.project)
    outfile_params = "./{0}/{0}_ASTparams.fits".format(settings.project)

    # if the SED file doesn't exist, create SEDs
    if not os.path.isfile(outfile_seds):

        print("Selecting SEDs for ASTs")

        if flux_bin_method:

            N_fluxes = settings.ast_n_flux_bins
            min_N_per_flux = settings.ast_n_per_flux_bin
            bins_outfile = "./{0}/{0}_ASTfluxbins.txt".format(settings.project)
            modelsedgrid_filename = "./{0}/{0}_seds.grid.hd5".format(settings.project)

            chosen_seds = pick_models_toothpick_style(
                modelsedgrid_filename,
                settings.filters,
                Nfilters,
                N_fluxes,
                min_N_per_flux,
                outfile=outfile_seds,
                outfile_params=outfile_params,
                bins_outfile=bins_outfile,
            )

        else:

            # construct magnitude cuts

            mag_cuts = settings.ast_maglimit

            if len(mag_cuts) == 1:
                tmp_cuts = mag_cuts
                min_mags = np.zeros(len(settings.filters))
                for k, filtername in enumerate(obsdata.filters):
                    sfiltername = obsdata.data.resolve_alias(filtername)
                    sfiltername = sfiltername.replace("rate", "vega")
                    sfiltername = sfiltername.replace("RATE", "VEGA")
                    (keep,) = np.where(obsdata[sfiltername] < 99.0)
                    min_mags[k] = np.percentile(obsdata[keep][sfiltername], 90.0)

                # max. mags from the gst observation cat.
                mag_cuts = min_mags + tmp_cuts

            N_models = settings.ast_models_selected_per_age

            chosen_seds = pick_models(
                modelsedgrid_filename,
                settings.filters,
                mag_cuts,
                Nfilter=Nfilters,
                N_stars=N_models,
                Nrealize=Nrealize,
                outfile=outfile_seds,
                outfile_params=outfile_params,
            )

    # if the SED file does exist, read them in
    else:
        print("Reading existing AST SEDs")
        chosen_seds = Table.read(outfile_seds, format="ascii")

    # --------------------
    # assign positions
    # --------------------

    # if we want ASTs with positions included (rather than just the fluxes from
    # the section above)
    if settings.ast_with_positions:

        print("Assigning positions to artifical stars")

        outfile = "./{0}/{0}_inputAST.txt".format(settings.project)

        # if we're replicating SEDs across source density or background bins
        if settings.ast_density_table is not None:
            make_ast_xy_list.pick_positions_from_map(
                obsdata,
                chosen_seds,
                settings.ast_density_table,
                settings.ast_N_bins,
                settings.ast_realization_per_model,
                outfile=outfile,
                refimage=settings.ast_reference_image,
                refimage_hdu=1,
                wcs_origin=1,
                Nrealize=1,
                set_coord_boundary=settings.ast_coord_boundary,
                region_from_filters="all",
            )

        # if we're not using SD/background maps, SEDs will be distributed
        # based on catalog sources
        else:
            make_ast_xy_list.pick_positions(
                obsdata,
                outfile,
                settings.ast_pixel_distribution,
                refimage=settings.ast_reference_image,
            )


if __name__ == "__main__":  # pragma: no cover
    # commandline parser
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "beast_settings_file",
        type=str,
        help="file name with beast settings",
    )
    parser.add_argument(
        "--random_seds",
        action="store_true",
        help="Randomly pick from the physicsmodel grid",
    )

    args = parser.parse_args()

    make_ast_inputs(
        beast_settings_info=args.beast_settings_file,
        flux_bin_method=not args.random_seds,
    )

    # print help if no arguments
    if not any(vars(args).values()):
        parser.print_help()
