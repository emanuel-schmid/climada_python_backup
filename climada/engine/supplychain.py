"""
This file is part of CLIMADA.

Copyright (C) 2017 ETH Zurich, CLIMADA contributors listed in AUTHORS.

CLIMADA is free software: you can redistribute it and/or modify it under the
terms of the GNU Lesser General Public License as published by the Free
Software Foundation, version 3.

CLIMADA is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along
with CLIMADA. If not, see <https://www.gnu.org/licenses/>.

---

Define the SupplyChain class.
"""

__all__ = ['SupplyChain']

import logging
import datetime as dt
from pathlib import Path
from tqdm import tqdm
import numpy as np
import pandas as pd
from iso3166 import countries_by_numeric
from climada.util import files_handler as u_fh
from climada.engine import Impact
from climada.util.constants import SYSTEM_DIR
from climada.entity.exposures.base import Exposures

LOGGER = logging.getLogger(__name__)
WIOD_FILE_LINK = 'http://www.wiod.org/protected3/data16/wiot_ROW/'

class SupplyChain():
    """SupplyChain definition. It provides methods for the entire supplychain-risk
    workflow and attributes holding the workflow's data and results.

    Attributes:
        mriot_data (np.array): 2-dim np.array of floats representing the data of
            a full multi-regional input-output table (mriot).
        countries_iso3 (np.array): similar to .countries, but containing the
            countries' respective iso3-codes.
        sectors (np.array): 1-dim np.array of strings containing the full
            list of sectors represented in the mriot, corresponding to the columns/
            rows of mriot_data. For these sectors risk calculations can be made.
        total_prod (np.array): 1-dim arrays of floats representing the total
            production value of each country/sector-pair, i.e. each sector's
            total production per country.
        mriot_type (str): short string describing the mriot used for analysis.
        cntry_pos (dict): dict with positions of all countries in the
            mriot table and output arrays.
        cntry_dir_imp (list): list with countries with direct impacts.
    Attributes storing results of risk calculations:
        years (np.array): 1-dim np.array containing all years for which impact
            calculations where made (in yyyy format).
        direct_impact (np.array): 2-dim np.array containing an impact-YEAR-set
            with direct impact per year on each country/sector-pair.
        direct_aai_agg (np.array): 1-dim np.array containing the average annual
            direct impact for each country/sector-pair.
        indirect_impact (np.array): 2-dim np.array containing an impact-YEAR-set
            with indirect impact per year on each country/sector-pair.
        indirect_aai_agg (np.array): 1-dim np.array containing the average annual
            indirect impact for each country/sector-pair.
        total_impact (np.array): 2-dim array containing an impact-year-set with
            total (i.e. sum direct+indirect) impact per year on each
            country/sector-pair.
        total_aai_agg (np.array): 1-dim np.array containing the average annual
            total impact for each country/sector-pair.
        io_data (dict): dictionary with four key:value-pairs:
            coefficients (np.array): 2-dim np.array containing the technical or
                allocation coefficient matrix, depending on employed io approach.
            inverse (np.array): 2-dim np.array containing Leontief or Ghosh
                inverse matrix, depending on employed io approach.
            io_approach (str): string informing about which io approach was
                used in calculation of indirect risk.
            risk_structure (np.array): 3-dim np.array containing for each year
                the risk relations between all sector/country-pairs.
        """
    def __init__(self):
        """Initialization"""
        self.mriot_data = np.array([], dtype='f')
        self.countries_iso3 = np.array([], dtype='str')
        self.sectors = np.array([], dtype='str')
        self.total_prod = np.array([], dtype='f')
        self.mriot_type = 'None'
        self.cntry_pos = {}

    def read_wiod(self, year=2014, file_folder=SYSTEM_DIR.joinpath('results')):
        """Read multi-regional input-output table of the WIOD project.
        See www.wiod.org and the following paper: Timmer, M. P., Dietzenbacher,
        E., Los, B., Stehrer, R. and de Vries, G. J. (2015), "An Illustrated
        User Guide to the World Input–Output Database: the Case of Global
        Automotive Production", Review of International Economics., 23: 575–605

        The function supports WIOD tables release available here:
            http://www.wiod.org/database/wiots16

        Parameters:
            year (int): Year of wiot table. Valid years go from 2000 to 2014.
                        Default 2014.
            file_path (str): Path to folder where the wiod table is stored.
                            Deafult is SYSTEM_DIR. If data are not present, they
                            will be downloaded in save_dir, i.e., ~/climada/data/results
                            If user-defined, user_data must be set to True
            Default values of the last four args allow reading the full wiot table.
        """

        file_name = 'WIOT{}_Nov16_ROW.xlsb'.format(year)
        file_folder = Path(file_folder)
        file_folder.mkdir(exist_ok=True)
        file_loc = file_folder / file_name

        if not file_loc in file_folder.iterdir():
            download_link = WIOD_FILE_LINK + file_name
            u_fh.download_file(download_link, download_dir=file_folder)
            LOGGER.info('Downloading WIOD table for year %s', year)
        mriot = pd.read_excel(file_loc, engine='pyxlsb')

        # hard-coded values based on the structure of the wiod tables
        col_sectors = 1
        col_iso3 = 2
        end_row_sectors = 61
        start_row, end_row = (5, 2469)
        start_col, end_col = (4, 2468)

        self.sectors = mriot.iloc[start_row:end_row_sectors, col_sectors].values
        self.countries_iso3 = mriot.iloc[start_row:end_row, col_iso3].unique()
        self.mriot_data = mriot.iloc[start_row:end_row,
                                     start_col:end_col].values
        self.total_prod = mriot.iloc[start_row:end_row, -1].values
        self.cntry_pos = {
            iso3: range(len(self.sectors)*i, len(self.sectors)*(i+1))
            for i, iso3 in enumerate(self.countries_iso3)
            }
        self.mriot_type = 'wiod'

    def calc_sector_direct_impact(self, hazard, exposure, imp_fun_set,
                                  sector_type='service', selected_subsec=None):
        """Calculate for each country/sector-combination the direct impact per year.
        I.e. compute one year impact set for each country/sector combination. Returns
        the notion of a supplychain year impact set, which is a dataframe with size
        (n years) * ((n countries)*(n sectors)).

        Parameters:
            hazard (Hazard): Hazard object for impact calculation.
            exposure (Exposures): Exposures object for impact calculation.
            imp_fun_set (ImpactFuncSet): Set of impact functions.
            selected_subsec (list): User-defined list with positions of the
                                    subsector to analyze. Default None.
            sector_type (str): If sec_subsec is not defined; it sets the start
                and end positions in the mriot tablefor some default sectors.
                Possible values are "service", "manufacturing", "agriculture"
                and "mining". Either sec_subsec or sector_type must be defined.
        """

        if not selected_subsec:
            built_in_subsec_pos = {'service': range(26, 56),
                                   'manufacturing': range(4, 23),
                                   'agriculture': range(0, 1),
                                   'mining': range(3, 4)}

            selected_subsec = built_in_subsec_pos[sector_type]

        dates = [
            dt.datetime.strptime(date, "%Y-%m-%d")
            for date in hazard.get_event_date()
            ]
        self.years = np.unique([date.year for date in dates])

        unique_regid_same_order = exposure.gdf.region_id.unique()   
        # n_subsecs = end_pos - init_pos
        self.direct_impact = np.zeros(shape=(len(self.years),
                                             len(self.countries_iso3)*len(self.sectors)))

        self.cntry_dir_imp = []
        for cntry in unique_regid_same_order:
            cntyr_exp = Exposures(exposure.gdf[exposure.gdf.region_id == cntry])
            cntyr_exp.check()

            # Normalize exposure
            total_ctry_value = cntyr_exp.gdf['value'].sum()
            cntyr_exp.gdf['value'] /= total_ctry_value

            # Calc impact for country
            imp = Impact()
            imp.calc(cntyr_exp, imp_fun_set, hazard)
            imp_year_set = np.array(list(imp.calc_impact_year_set(imp).values()))

            # Total production of country
            cntry_iso3 = countries_by_numeric.get(str(cntry)).alpha3
            idx_country = np.where(self.countries_iso3 == cntry_iso3)[0]

            if not idx_country.size > 0.:
                cntry_iso3 = 'ROW'

            self.cntry_dir_imp.append(cntry_iso3)
            
            subsec_cntry_pos = np.array(selected_subsec) + self.cntry_pos[cntry_iso3][0]
            subsec_cntry_prod = self.mriot_data[subsec_cntry_pos].sum(axis=1)

            imp_year_set = np.repeat(imp_year_set, len(selected_subsec)
                                     ).reshape(len(self.years), 
                                               len(selected_subsec))
            direct_impact_cntry = np.multiply(imp_year_set, subsec_cntry_prod)

            # Sum needed below in case of many ROWs, which are aggregated into 
            # one country as per WIOD table.
            self.direct_impact[:, subsec_cntry_pos] += direct_impact_cntry.astype(np.float32)

        # average impact across years
        self.direct_aai_agg = self.direct_impact.mean(axis=0)

    def calc_indirect_impact(self, io_approach='ghosh'):
        """Estimate indirect impact based on direct impact using input-output (IO)
        methodology. There are three IO approaches to choose from (see Parameters).
            [1] Standard Input-Output (IO) Model;
                W. W. Leontief, Output, employment, consumption, and investment,
                The Quarterly Journal of Economics 58 (2) 290?314, 1944
            [2] Ghosh Model;
                Ghosh, A., Input-Output Approach in an Allocation System,
                Economica, New Series, 25, no. 97: 58-64. doi:10.2307/2550694, 1958
            [3] Environmentally Extended Input-Output Analysis (EEIOA);
                Kitzes, J., An Introduction to Environmentally-Extended Input-Output Analysis,
                Resources 2013, 2, 489-503; doi:10.3390/resources2040489, 2013
        Parameters:
            io_approach (str): string specifying which IO approach the user would
                like to use. Either 'leontief', 'ghosh' (default) or 'eeioa'.
        """

        io_switch = {'leontief': self._leontief_calc, 'ghosh': self._ghosh_calc,
                     'eeioa': self._eeioa_calc}

        # Compute coefficients based on selected IO approach
        coefficients = np.zeros_like(self.mriot_data, dtype=np.float32)
        if io_approach in ['leontief', 'eeioa']:
            for col_i, col in enumerate(self.mriot_data.T):
                if self.total_prod[col_i] > 0:
                    coefficients[:, col_i] = np.divide(col, self.total_prod[col_i])
                else:
                    coefficients[:, col_i] = 0
        else:
            for row_i, row in enumerate(self.mriot_data):
                if self.total_prod[row_i] > 0:
                    coefficients[row_i, :] = np.divide(row, self.total_prod[row_i])
                else:
                    coefficients[row_i, :] = 0

        inverse = np.linalg.inv(np.identity(len(self.mriot_data)) - coefficients)
        inverse = inverse.astype(np.float32)

        # Calculate indirect impacts
        self.indirect_impact = np.zeros_like(self.direct_impact, dtype=np.float32)
        risk_structure = np.zeros(np.shape(self.mriot_data) + (len(self.years),),
                                  dtype=np.float32)

        # Loop over years indices:
        for year_i, _ in enumerate(tqdm(self.years)):
            direct_impact_yearly = self.direct_impact[year_i, :]

            direct_intensity = np.zeros_like(direct_impact_yearly)
            for idx, (impact, production) in enumerate(zip(direct_impact_yearly,
                                                           self.total_prod)):
                if production > 0:
                    direct_intensity[idx] = impact/production
                else:
                    direct_intensity[idx] = 0

            # Calculate risk structure based on selected IO approach
            risk_structure = io_switch[io_approach](direct_intensity, inverse,
                                                    risk_structure, year_i)
            # Total indirect risk per sector/country-combination:
            self.indirect_impact[year_i, :] = np.nansum(
                risk_structure[:, :, year_i], axis=0)

        self.indirect_aai_agg = self.indirect_impact.mean(axis=0)

        self.io_data = {}
        self.io_data.update({'coefficients': coefficients, 'inverse': inverse,
                             'risk_structure' : risk_structure, 
                             'io_approach' : io_approach})

    def calc_total_impact(self):
        """Calculates the total impact and total average annual impact on each
        country/sector """
        self.total_impact = self.indirect_impact + self.direct_impact
        self.total_aai_agg = self.total_impact.mean(axis=0)

    def _leontief_calc(self, direct_intensity, inverse, risk_structure, year_i):
        """It calculates the risk_structure based on the Leontief approach"""
        demand = self.total_prod - np.nansum(self.mriot_data, axis=1)
        degr_demand = direct_intensity*demand
        for idx, row in enumerate(inverse):
            risk_structure[:, idx, year_i] = row * degr_demand
        return risk_structure

    def _ghosh_calc(self, direct_intensity, inverse, risk_structure, year_i):
        """It calculates the risk_structure based on the Ghosh approach"""
        value_added = self.total_prod - np.nansum(self.mriot_data, axis=0)
        degr_value_added = np.maximum(direct_intensity*value_added,\
                                      np.zeros_like(value_added))
        for idx, col in enumerate(inverse.T):
           # Here, we iterate across columns of inverse (hence transpose used).
            risk_structure[:, idx, year_i] = degr_value_added * col
        return risk_structure

    def _eeioa_calc(self, direct_intensity, inverse, risk_structure, year_i):
        """It calculates the risk_structure based on the EEIOA approach"""

        for idx, col in enumerate(inverse.T):
            risk_structure[:, idx, year_i] = (direct_intensity * col) * self.total_prod[idx]
        return risk_structure
