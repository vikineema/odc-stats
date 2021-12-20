"""
Fractional Cover Percentiles
"""
from functools import partial
from typing import Tuple
from itertools import product
import xarray as xr
import numpy as np
from odc.algo import keep_good_only
from odc.algo._percentile import xr_quantile_bands
from odc.algo._masking import _xr_fuse, _or_fuser, _fuse_mean_np, _fuse_or_np
from ._registry import StatsPluginInterface, register

NODATA = 255


class StatsFCP(StatsPluginInterface):

    NAME = "ga_fc_percentiles"
    SHORT_NAME = NAME
    VERSION = "0.0.2"
    PRODUCT_FAMILY = "fc_percentiles"

    def __init__(self, **kwargs):
        super().__init__(input_bands=["water", "pv", "bs", "npv", "ue"], **kwargs)

    @property
    def measurements(self) -> Tuple[str, ...]:
        _measurements = [
            f"{b}_pc_{p}" for b, p in product(["pv", "bs", "npv"], ["10", "50", "90"])
        ]
        _measurements.append("qa")
        _measurements.append("count_valid")
        return _measurements

    def native_transform(self, xx):
        """
        Loads data in its native projection. It performs the following:

        1. Load all fc and WOfS bands
        2. Set the high terrain slope flag to 0
        3. Set all pixels that are not clear and dry to NODATA
        4. Calculate the clear wet pixels
        5. Drop the WOfS band
        """

        water = xx.water & 0b1110_1111
        xx = xx.drop_vars(["water"])

        unmixing_error_lt_30 = xx.ue < 30
        xx = xx.drop_vars(["ue"])

        dry = water == 0
        dry_and_ue_lt_30 = dry & unmixing_error_lt_30

        xx = keep_good_only(xx, dry_and_ue_lt_30, nodata=NODATA)
        xx["wet"] = water == 128

        return xx

    def fuser(self, xx):
        wet = xx["wet"]
        xx = _xr_fuse(xx.drop_vars(["wet"]), partial(_fuse_mean_np, nodata=NODATA), "")

        band, *bands = xx.data_vars.keys()
        all_bands_invalid = xx[band] == NODATA
        for band in bands:
            all_bands_invalid &= xx[band] == NODATA

        xx["wet"] = _xr_fuse(wet, _fuse_or_np, wet.name) & all_bands_invalid
        return xx

    def reduce(self, xx: xr.Dataset) -> xr.Dataset:
        # (!all_bands_valid) & is_ever_wet => 0
        # (!all_bands_valid) & (!is_ever_wet) => 1
        # all_bands_valid => 2

        wet = xx["wet"]
        xx = xx.drop_vars(["wet"])

        yy = xr_quantile_bands(xx, [0.1, 0.5, 0.9], nodata=NODATA)
        is_ever_wet = _or_fuser(wet).squeeze(wet.dims[0], drop=True)

        band, *bands = yy.data_vars.keys()
        all_bands_valid = yy[band] != NODATA
        for band in bands:
            all_bands_valid &= yy[band] != NODATA

        all_bands_valid = all_bands_valid.astype(np.uint8)
        is_ever_wet = is_ever_wet.astype(np.uint8)
        yy["qa"] = 1 + all_bands_valid - is_ever_wet * (1 - all_bands_valid)
        yy["count_valid"] = all_bands_valid

        return yy


register("fc-percentiles", StatsFCP)
