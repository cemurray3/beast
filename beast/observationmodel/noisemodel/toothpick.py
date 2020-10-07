import math

import numpy as np

from tqdm import tqdm

from beast.observationmodel.noisemodel.noisemodel import NoiseModel
from beast.observationmodel.vega import Vega

from beast.observationmodel.noisemodel.helpers import convert_dict_to_structured_ndarray

__all__ = ["MultiFilterASTs"]


class MultiFilterASTs(NoiseModel):
    """
    A noise model for based Artificial Star Tests (ASTs) that are provided
    as one single table.

    The noise model is computed in equally spaced bins in log flux space to
    avoid injecting noise when the ASTs grossly oversample the model space.
    This is the case for single band ASTs - this is always the case for the
    BEAST toothpick noise model.

    Attributes
    ----------
    astfile : str
        file containing the ASTs
    filters : list
        sequence of filter names
    filter_aliases : dict
        alias of filter names between internal and external names
    """

    def __init__(self, astfile, filters, vega_fname=None, *args, **kwargs):
        """
        Parameters
        ----------
        astfile : str
            file containing the ASTs
        filters : list
            filters using the internal namings (obs_inst_band)
        vega_fname : str, optional
            filename of the vega database
        """
        super().__init__(astfile, *args, **kwargs)
        self.setFilters(filters, vega_fname=vega_fname)

        self._fluxes = None
        self._biases = None
        self._sigmas = None
        self._compls = None

    def setFilters(self, filters, vega_fname=None):
        """
        Set the filters and update the vega reference for the conversions

        Parameters
        ----------
        filters : list
            filters using the internally normalized namings
        vega_fname : str, optional
            filename of the vega database
        """
        self.filters = filters

        # ASTs inputs are in vega mag whereas models are in flux units
        #     for optimization purpose: pre-compute
        with Vega(source=vega_fname) as v:
            _, vega_flux, _ = v.getFlux(filters)

        self.vega_flux = vega_flux

    def set_data_mappings(
        self, in_pair=("in", "in"), out_pair=("out", "vega"), upcase=False
    ):
        """
        Specify the mapping directly with the interface to PHAT-like ASTs

        Parameters
        ----------
        in_pair, out_pair : tuple, optional
            (in, out) strings giving the ending string mappings
            defaults: (in, in) aliases internal HST_WFC3_F275W_in to exernal f275w_in
            and (out, vega) aliases internal HST_WFC3_F275W_out to external f275w_vega
        upcase : bool, optional
            set to make the external name all uppercase
        """
        for k in self.filters:
            external_in = k.split("_")[-1] + "_" + in_pair[1]
            external_out = k.split("_")[-1] + "_" + out_pair[1]
            if upcase:
                external_in = external_in.upper()
                external_out = external_out.upper()
            else:
                external_in = external_in.lower()
                external_out = external_out.lower()
            self.filter_aliases[k + "_in"] = external_in
            self.filter_aliases[k + "_out"] = external_out

    def _compute_sigma_bins(
        self,
        magflux_in,
        magflux_out,
        nbins=30,
        min_per_bin=10,
        completeness_mag_cut=80,
        name_prefix=None,
        asarray=False,
        compute_stddev=False,
    ):
        """
        Computes sigma estimate for each bin, store the result in a
        dictionary. Estimation performed using percentile-based method
        (by default) where sigma = (84th-16th)/2 and avg bias = 50th.
        Alternate method: use mean and stddev.

        Parameters
        ----------
        magflux_in : ndarray
             AST input mag or flux

        magflux_out : ndarray
             AST output mag or flux

        completeness_mag_cut : float
            magnitude at which consider a star not recovered
            set to -1 if the magflux_out is in fluxes (not magnitudes)

        nbins : int, optional
            Number of logrithmically spaced bins between the min/max values

        min_per_bin : int, optional
            Number of recovered ASTs required per bin for computation

        name_prefix : str, optional
            if set, all output names in the final structure will start with
            this prefix.

        asarray : bool, optional
            if set returns a structured ndarray instead of a dictionary

        compute_stddev : bool, optional
            if True, uses np.mean()+np.std() to estimate avg bias+sigma;
            if False (default), uses np.percentiles

        Returns
        -------
        d : dict or np.recarray
            dictionary or named array containing the statistics

        """
        if name_prefix is None:
            name_prefix = ""
        else:
            if name_prefix[-1] != "_":
                name_prefix += "_"

        # check if any NaNs are present, remove if they are
        # NaNs can be present due to the AST pipeline or in cases where
        # there is missing data (e.g., chip gaps)
        if np.any(np.isnan(magflux_in)):
            gvals = np.isfinite(magflux_in) & np.isfinite(magflux_out)
            magflux_in = magflux_in[gvals]
            magflux_out = magflux_out[gvals]
            print("removing NaNs")

        # convert the AST output from magnitudes to fluxes if needed
        #  this is designated by setting the completeness_mag_cut to a
        #  negative number
        #    good_indxs gives the list of recovered sources
        if completeness_mag_cut > 0:
            # first remove cases that have input magnitudes below the cut
            #   not sure why this is possible, but they exist and contain
            #   *no information* as mag_in = mag_out = 99.99
            (good_in_indxs,) = np.where(magflux_in < completeness_mag_cut)
            if len(good_in_indxs) < len(magflux_in):
                magflux_in = magflux_in[good_in_indxs]
                magflux_out = magflux_out[good_in_indxs]

            # now convert from input mags to normalized vega fluxes
            flux_out = 10 ** (-0.4 * magflux_out)
            (bad_indxs,) = np.where(magflux_out >= completeness_mag_cut)
            flux_out[bad_indxs] = 0.0
        else:
            flux_out = magflux_out

        # convert the AST input from magnitudes to fluxes
        # always convert the magflux_in to fluxes (the way the ASTs are
        # reported)
        flux_in = 10 ** (-0.4 * magflux_in)

        # storage the storage of the results
        ave_flux_in = np.zeros(nbins, dtype=float)
        ave_bias = np.zeros(nbins, dtype=float)
        std_bias = np.zeros(nbins, dtype=float)
        completeness = np.zeros(nbins, dtype=float)
        good_bins = np.zeros(nbins, dtype=int)

        # get the indexs to the recovered fluxes
        (good_indxs,) = np.where(flux_out != 0.0)

        ast_minmax = np.empty(2)
        ast_minmax[0] = np.amin(flux_in[good_indxs])
        ast_minmax[1] = np.amax(flux_in[good_indxs])

        # setup the bins (done in log units due to dynamic range)
        #  add a very small value to the max to make sure all the data is
        #  included
        min_flux = math.log10(min(flux_in))
        max_flux = math.log10(max(flux_in) * 1.000001)
        delta_flux = (max_flux - min_flux) / float(nbins)
        bin_min_vals = min_flux + np.arange(nbins) * delta_flux
        bin_max_vals = bin_min_vals + delta_flux
        bin_ave_vals = 0.5 * (bin_min_vals + bin_max_vals)

        # convert the bin min/max value to linear space for computational ease
        bin_min_vals = 10 ** bin_min_vals
        bin_max_vals = 10 ** bin_max_vals
        bin_ave_vals = 10 ** bin_ave_vals

        for i in range(nbins):
            (bindxs,) = np.where(
                (flux_in >= bin_min_vals[i]) & (flux_in < bin_max_vals[i])
            )
            n_bindxs = len(bindxs)
            if n_bindxs > 0:
                bin_flux_in = flux_in[bindxs]
                bin_flux_out = flux_out[bindxs]
                # compute completeness
                (g_bindxs,) = np.where(bin_flux_out != 0.0)
                n_g_bindxs = len(g_bindxs)
                completeness[i] = n_g_bindxs / float(n_bindxs)
                if n_g_bindxs > min_per_bin:
                    good_bins[i] = 1
                    ave_flux_in[i] = np.mean(bin_flux_in)
                    bin_bias_flux = bin_flux_out[g_bindxs] - bin_flux_in[g_bindxs]
                    if compute_stddev:
                        # compute sigma via mean/stddev
                        ave_bias[i] = np.mean(bin_bias_flux)
                        std_bias[i] = np.std(bin_bias_flux)
                    else:
                        # compute sigma via percentiles
                        # ave = 50th; std = (84th-16th)/2
                        flux_percent_out = np.percentile(
                            bin_bias_flux, [16.0, 50.0, 84.0]
                        )
                        ave_bias[i] = flux_percent_out[1]
                        std_bias[i] = (flux_percent_out[2] - flux_percent_out[0]) / 2.0

        # only pass back the bins with non-zero results
        (gindxs,) = np.where(good_bins == 1)

        d = {
            name_prefix + "FLUX_STD": std_bias[gindxs],
            name_prefix + "FLUX_BIAS": ave_bias[gindxs],
            name_prefix + "FLUX_IN": bin_ave_vals[gindxs],
            name_prefix + "FLUX_OUT": bin_ave_vals[gindxs] + ave_bias[gindxs],
            name_prefix + "COMPLETENESS": completeness[gindxs],
            name_prefix + "MINMAX": ast_minmax,
        }

        if asarray:
            return convert_dict_to_structured_ndarray(d)
        else:
            return d

    def fit(self, nbins=50, completeness_mag_cut=80, progress=True):
        """
        Alias of fit_bins
        """
        return self.fit_bins(
            nbins=nbins, completeness_mag_cut=completeness_mag_cut, progress=progress
        )

    def fit_bins(self, nbins=50, completeness_mag_cut=80, progress=True):
        """
        Compute the necessary statistics before evaluating the noise model

        Parameters
        ----------
        completeness_mag_cut : float
            magnitude at which consider a star not recovered

        progress : bool, optional
            if set, display a progress bar

        .. see also: :func:`_compute_stddev`
        """

        shape = nbins, len(self.filters)

        self._fluxes = np.zeros(shape, dtype=float)
        self._biases = np.zeros(shape, dtype=float)
        self._sigmas = np.zeros(shape, dtype=float)
        self._compls = np.zeros(shape, dtype=float)
        self._nasts = np.zeros(shape[1], dtype=int)
        self._minmax_asts = np.zeros((2, shape[1]), dtype=float)

        if progress is True:
            it = tqdm(self.filters, desc="Fitting model")
        else:
            it = self.filters

        for e, filterk in enumerate(it):

            mag_in = self.data[self.filter_aliases[filterk + "_in"]]
            magflux_out = self.data[self.filter_aliases[filterk + "_out"]]

            d = self._compute_sigma_bins(
                mag_in,
                magflux_out,
                nbins=nbins,
                completeness_mag_cut=completeness_mag_cut,
            )

            ncurasts = len(d["FLUX_IN"])
            self._fluxes[0:ncurasts, e] = d["FLUX_IN"] * self.vega_flux[e]
            self._sigmas[0:ncurasts, e] = d["FLUX_STD"] * self.vega_flux[e]
            self._biases[0:ncurasts, e] = d["FLUX_BIAS"] * self.vega_flux[e]
            self._compls[0:ncurasts, e] = d["COMPLETENESS"]
            self._nasts[e] = ncurasts
            self._minmax_asts[:, e] = d["MINMAX"] * self.vega_flux[e]

            del d

    def interpolate(self, sedgrid, progress=True):
        """
        Interpolate the results of the ASTs on a model grid

        Parameters
        ----------
        sedgrid : beast.core.grid type
            model grid to interpolate AST results on

        progress : bool, optional
            if set, display a progress bar

        Returns
        -------
        bias : ndarray
            bias table of the models

        sigma : ndarray
            dispersion table of the models

        comp : ndarray
            completeness table per model
        """
        flux = sedgrid.seds
        N, M = flux.shape

        if M != len(self.filters):
            raise AttributeError(
                "the grid of models does not seem to"
                + "be defined with the same number of filters"
            )

        bias = np.empty((N, M), dtype=float)
        sigma = np.empty((N, M), dtype=float)
        compl = np.empty((N, M), dtype=float)

        if progress is True:
            it = tqdm(list(range(M)), desc="Evaluating model")
        else:
            it = list(range(M))

        for i in it:

            ncurasts = self._nasts[i]
            _fluxes = self._fluxes[0:ncurasts, i]
            _biases = self._biases[0:ncurasts, i]
            _sigmas = self._sigmas[0:ncurasts, i]
            _compls = self._compls[0:ncurasts, i]

            arg_sort = np.argsort(_fluxes)
            _fluxes = _fluxes[arg_sort]

            bias[:, i] = np.interp(
                flux[:, i], _fluxes, _biases[arg_sort], left=0.0, right=0.0
            )
            sigma[:, i] = np.interp(
                flux[:, i], _fluxes, _sigmas[arg_sort], left=0.0, right=0.0
            )
            compl[:, i] = np.interp(
                flux[:, i], _fluxes, _compls[arg_sort], left=0.0, right=0.0
            )

        return (bias, sigma, compl)

    def __call__(self, sedgrid, **kwargs):
        return self.interpolate(sedgrid, **kwargs)
