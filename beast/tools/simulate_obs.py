import argparse
# import numpy as np

# from astropy.table import Table, Column

from beast.physicsmodel.grid import FileSEDGrid
import beast.observationmodel.noisemodel.generic_noisemodel as noisemodel
from beast.observationmodel.observations import gen_SimObs_from_sedgrid


if __name__ == '__main__':

    # commandline parser
    parser = argparse.ArgumentParser()
    parser.add_argument("physgrid",
                        help='filename of physics grid')
    parser.add_argument("obsgrid",
                        help='filename of observation/nosie grid')
    parser.add_argument("outfile",
                        help='filename for simulated observations')
    parser.add_argument('--nsim', default=100,
                        help='number of simulated objects')
    parser.add_argument('--compl_filter', default='F475W',
                        help='filter name to use for completeness')
    args = parser.parse_args()

    # get the physics model grid - includes priors
    modelsedgrid = FileSEDGrid(args.physgrid)

    # read in the noise model - includes bias, unc, and completeness
    noisegrid = noisemodel.get_noisemodelcat(args.obsgrid)

    simtable = gen_SimObs_from_sedgrid(modelsedgrid, noisegrid,
                                       nsim=args.nsim,
                                       compl_filter=args.compl_filter)

    simtable.write(args.outfile, overwrite=True)
