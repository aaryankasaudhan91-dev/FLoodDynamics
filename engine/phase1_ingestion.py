import math
import time
import logging
from datetime import datetime, timezone
log = logging.getLogger("floodguard.ingestion")
# Handles CWC river-level and reservoir readings for the Mithi catchment.
class CWCIndiaWRISEngine:
    def __init__(self):
        # Gauge stations used for the Mithi River and its tidal outfall.
        # Kurla station is one of the monitored points along the river.
        # Mahim Creek represents the downstream tidal outfall.
        self.stations = {
            "CWC_GAUGE_MITHI_01": {
                "name": "Mithi River - Kurla Station",
                "lat": 19.0684,
                "lon": 72.8856,
                "elevation": 3.2,
                "h0": 0.85,          # riverbed zero-flow stage
                "cr": 48.5,          # rating curve multiplier
                "beta": 1.68,        # exponent calibrated post-2005 deluge
                "warning_level": 3.90,
                "danger_level": 4.80, # BMC alerts sent when water touches 4.8m
                "record_hfl": 5.42,  # July 26, 2005 peak level at Kurla
                "current_stage": 2.15,
                "last_stage": 2.10,
                "last_t": time.time() - 900 # 15-min polling interval
            },
            "CWC_GAUGE_MAHIM_02": {
                "name": "Mahim Creek Outfall",
                "lat": 19.0410,
                "lon": 72.8420,
                "elevation": 1.5,
                "h0": 0.20,
                "cr": 55.0,
                "beta": 1.72,
                "warning_level": 3.20,
                "danger_level": 4.10,
                "record_hfl": 4.85,
                "current_stage": 1.65,
                "last_stage": 1.60,
                "last_t": time.time() - 900
            }
        }

        # BMC water-supply reservoirs in and around Sanjay Gandhi National Park.
        # Vihar Lake is included because its outflow is connected to the upper Mithi catchment.
        self.reservoirs = {
            "RES_VIHAR_MUMBAI": {
                "name": "Vihar Lake",
                "frl": 80.42,
                "mwl": 81.10,
                "level": 79.15,
                "gross_bcm": 0.091,
                "live_bcm": 0.082,
                "util": 90.1,
                "inflow": 142.0,
                "outflow": 35.0  # spillway discharge into Mithi
            },
            "RES_TULSI_MUMBAI": {
                "name": "Tulsi Lake",
                "frl": 139.17,
                "mwl": 139.60,
                "level": 138.80,
                "gross_bcm": 0.024,
                "live_bcm": 0.021,
                "util": 87.5,
                "inflow": 45.0,
                "outflow": 12.0
            }
        }

    def compute_discharge(self, stage: float, h_0: float = 0.85, c_r: float = 48.5, beta: float = 1.68) -> float:
        # Estimate discharge from the current stage using the configured rating curve.
        eff_head = float(stage) - float(h_0)
        if eff_head <= 0.0:
            return 0.0
        return round(float(c_r) * (eff_head ** float(beta)), 2)

    # Keep a descriptive alias for callers that use the rating-curve terminology.
    def calc_rating_curve_flow(self, stage_h: float, bed_datum: float, c_rating: float, exp_beta: float) -> float:
        return self.compute_discharge(stage_h, bed_datum, c_rating, exp_beta)

    def get_station_observation(self, station_code: str = "CWC_GAUGE_MITHI_01", stage_override: float = None) -> dict:
        stn = self.stations.get(station_code)
        if not stn:
            stn = self.stations["CWC_GAUGE_MITHI_01"]

        # Use the supplied simulated stage when one is available.
        cur_stage = float(stage_override) if stage_override is not None else float(stn["current_stage"])
        q_cumecs = self.compute_discharge(cur_stage, stn["h0"], stn["cr"], stn["beta"])

        # Estimate how quickly the water level has changed since the previous reading.
        elapsed_hr = max(0.005, (time.time() - stn["last_t"]) / 3600.0)
        delta_h = cur_stage - stn["last_stage"]
        rise_rate = round(delta_h / elapsed_hr, 2)

        # Compare the current level with the configured warning and danger thresholds.
        if cur_stage >= stn["danger_level"]:
            alarm = "DANGER"
        elif cur_stage >= stn["warning_level"]:
            alarm = "WARNING"
        else:
            alarm = "NORMAL"

        return {
            "agency": "CWC",
            "basin_code": "CWC_BASIN_MITHI_01",
            "sub_basin": "Mithi_Estuary",
            "station_code": station_code,
            "station_name": stn["name"],
            "geo_coordinates": {
                "latitude": stn["lat"],
                "longitude": stn["lon"],
                "elevation_m_msl": stn["elevation"]
            },
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "telemetry_type": "RADAR_LEVEL_SENSOR",
            "hydrological_data": {
                "water_level_m_msl": round(cur_stage, 2),
                "discharge_cumecs": q_cumecs,
                "rate_of_rise_m_per_hr": rise_rate,
                "warning_level_m_msl": stn["warning_level"],
                "danger_level_m_msl": stn["danger_level"],
                "highest_flood_level_hfl": {
                    "level_m_msl": stn["record_hfl"],
                    "recorded_date": "2005-07-26"
                }
            },
            "qc_flags": {
                "sensor_health": "NOMINAL",
                "battery_volts": 12.6,
                "acoustic_confidence_pct": 98
            },
            "status": alarm
        }

    def get_reservoir_status(self, code: str = "RES_VIHAR_MUMBAI") -> dict:
        res = self.reservoirs.get(code, self.reservoirs["RES_VIHAR_MUMBAI"])
        return {
            "agency": "CWC",
            "reservoir_code": code,
            "name": res["name"],
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "storage_metrics": {
                "full_reservoir_level_frl_m": res["frl"],
                "maximum_water_level_mwl_m": res["mwl"],
                "current_water_level_m": res["level"],
                "gross_storage_capacity_bcm": res["gross_bcm"],
                "current_live_storage_bcm": res["live_bcm"],
                "storage_capacity_utilization_pct": res["util"],
                "inflow_cumecs": res["inflow"],
                "spillway_outflow_cumecs": res["outflow"]
            }
        }


# Uses radar observations and a simple short-range nowcast.
class IMDWeatherEngine:
    # Empirical Z-R relationships used to convert radar reflectivity to rainfall rate.
    # The coefficients are grouped by the assumed precipitation regime.
    RADAR_REGIMES = {
        "stratiform": {"a": 200.0, "b": 1.60},
        "convective": {"a": 300.0, "b": 1.40},
        "cyclonic":   {"a": 150.0, "b": 1.80}
    }

    def marshall_palmer_inversion(self, dbz: float, regime: str = "convective") -> float:
        # Treat very weak echoes as no measurable rainfall for this calculation.
        if dbz is None or dbz <= 12.0:
            return 0.0

        coeffs = self.RADAR_REGIMES.get(str(regime).lower(), self.RADAR_REGIMES["convective"])
        a, b = coeffs["a"], coeffs["b"]

        # Convert dBZ to linear reflectivity before applying the selected relationship.
        z_linear = 10.0 ** (float(dbz) / 10.0)
        rain_rate = (z_linear / a) ** (1.0 / b)
        return round(float(rain_rate), 2)

    def is_ground_clutter(self, dbz: float, velocity_m_s: float, rho_hv: float = 0.95) -> tuple:
        # Flag strong echoes that look stationary and are therefore likely to be ground clutter.
        if abs(velocity_m_s) < 0.20 and dbz > 40.0:
            return True, "Doppler velocity near zero with high reflectivity indicates building/hill clutter"
        if rho_hv < 0.85:
            # A low RhoHV value is treated as another indication of a non-weather target.
            return True, "Dual-pol RhoHV < 0.85 confirms non-hydrometeor scatterer"
        return False, "Echo passed Doppler & dual-polarization sanity check"

    def polar_to_cartesian(self, range_km: float, azimuth_deg: float, elevation_deg: float = 0.5) -> tuple:
        # Approximate the radar beam position using the standard 4/3 Earth-radius model.
        r = range_km * 1000.0
        elev_rad = math.radians(elevation_deg)
        azim_rad = math.radians(azimuth_deg)

        x_m = r * math.cos(elev_rad) * math.sin(azim_rad)
        y_m = r * math.cos(elev_rad) * math.cos(azim_rad)
        # Approximate antenna height above mean sea level.
        beam_h = 45.0 + (r * math.sin(elev_rad)) + ((r ** 2) / (2.0 * (4.0 / 3.0) * 6371000.0))
        return round(x_m, 1), round(y_m, 1), round(beam_h, 1)

    def get_nowcast_alert(self, current_rain_rate: float) -> dict:
        t_now = datetime.now(timezone.utc)
        is_severe = current_rain_rate >= 45.0 # IMD heavy rainfall alert threshold

        # Approximate boundary used for the Dadar-Hindmata low-lying catchment.
        hindmata_box = [
            [19.005, 72.835], [19.025, 72.835],
            [19.025, 72.855], [19.005, 72.855], [19.005, 72.835]
        ]

        nowcast_id = f"IMD-NC-{t_now.strftime('%Y%m%d')}-MH-MUM-001"
        valid_until = datetime.fromtimestamp(t_now.timestamp() + 10800, timezone.utc).isoformat()

        return {
            "alert_type": "IMD_NOWCAST_FLASH_FLOOD",
            "identifier": nowcast_id,
            "sent_time_utc": t_now.isoformat(),
            "valid_until_utc": valid_until,
            "severity": "WARNING" if is_severe else "ADVISORY",
            "certainty": "VERY_LIKELY" if is_severe else "POSSIBLE",
            "affected_region": {
                "state": "Maharashtra",
                "district": "Mumbai Suburban",
                "basin": "Dadar - Hindmata Urban Catchment",
                "coordinates": hindmata_box
            },
            "quantitative_forecast": {
                "expected_rainfall_3hr_mm": round(current_rain_rate * 2.8, 1),
                "surface_wind_gust_kmph": 65.0 if is_severe else 25.0,
                "hazard_profile": "URBAN_FLASH_FLOOD_LOW_LYING_WATERLOGGING"
            }
        }

    def get_live_rainfall(self) -> dict:
        try:
            import urllib.request, json
            # Real live Mumbai meteorological feed (Santacruz/Bandra-Kurla grid)
            url = "https://api.open-meteo.com/v1/forecast?latitude=19.076&longitude=72.877&current=precipitation,rain,weather_code,wind_speed_10m"
            req = urllib.request.Request(url, headers={"User-Agent": "FloodGuard/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                cur = data.get("current", {})
                r = float(cur.get("precipitation", 0.0) or cur.get("rain", 0.0))
                w = float(cur.get("wind_speed_10m", 0.0))
                return {
                    "online": True,
                    "rain_mm_hr": r,
                    "wind_kmph": w,
                    "source": "Live IMD/WMO AWS Feed (Mumbai Grid 19.08N, 72.85E)",
                    "timestamp": cur.get("time")
                }
        except Exception as err:
            return {"online": False, "error": str(err), "rain_mm_hr": 0.0}


# Basic DEM conditioning: fill local sinks and reinforce mapped drainage paths.
class ISROBhuvanSpatialEngine:
    def hydro_condition(self, grid: list, stream_mask: list = None, burn_depth: float = 1.2) -> dict:
        if not grid or not isinstance(grid, list):
            return {"error": "Invalid elevation raster grid"}

        n_rows, n_cols = len(grid), len(grid[0]) if grid else 0
        dem = [row[:] for row in grid]

        # Fill simple interior depressions in the elevation grid.
        pits_filled = 0
        for r in range(1, n_rows - 1):
            for c in range(1, n_cols - 1):
                min_nbr = min(dem[r-1][c], dem[r+1][c], dem[r][c-1], dem[r][c+1])
                if dem[r][c] < min_nbr:
                    dem[r][c] = min_nbr
                    pits_filled += 1

        # Lower cells that fall on known drainage paths.
        burned_cells = 0
        if stream_mask and len(stream_mask) == n_rows:
            for r in range(n_rows):
                for c in range(n_cols):
                    if stream_mask[r][c]:
                        dem[r][c] = round(dem[r][c] - float(burn_depth), 2)
                        burned_cells += 1

        return {
            "grid_size": f"{n_rows}x{n_cols}",
            "sinks_filled": pits_filled,
            "streams_burned": burned_cells,
            "burn_depth_m": burn_depth,
            "output_grid": dem
        }


# Convert an ellipsoidal height to an orthometric height using the configured geoid value.
class SurveyOfIndiaCORSEngine:
    # Configured geoid undulation used for the Mumbai calculation.
    MUMBAI_GEOID_N = -42.85

    def calibrate_height(self, h_wgs84: float) -> float:
        # Orthometric H = Ellipsoidal h - Geoid N
        return round(float(h_wgs84) - self.MUMBAI_GEOID_N, 3)


# Clean incoming satellite rainfall-rate values.
class ISROMOSDACPrecipEngine:
    def clean_rain_rate(self, raw_rate: float) -> float:
        # Treat missing, invalid, or negative satellite values as unavailable rainfall.
        if raw_rate is None or math.isnan(raw_rate) or raw_rate < 0 or raw_rate == -999.0:
            return 0.0
        # Keep the returned value within the configured upper bound.
        return min(300.0, round(float(raw_rate), 2))


# Handles storm-water drainage telemetry from the municipal SCADA layer.
class MunicipalSCADAEngine:
    def __init__(self):
        # Pumping stations included in the monitored drainage network.
        self.pumps = {
            "Britannia": {"capacity_cumecs": 36.0, "active": 6, "total": 6, "status": "RUNNING"},
            "Lovegrove": {"capacity_cumecs": 45.0, "active": 8, "total": 8, "status": "RUNNING"},
            "Cleveland": {"capacity_cumecs": 30.0, "active": 5, "total": 6, "status": "RUNNING"},
            "Haji Ali":  {"capacity_cumecs": 24.0, "active": 4, "total": 4, "status": "RUNNING"}
        }

    def get_drain_readings(self, rain_mm_hr: float = 25.0, tide_m: float = 2.0) -> dict:
        # Estimate culvert depth from rainfall and tide inputs using the configured relationship.
        drain_depth = round(min(5.20, 1.60 + (float(rain_mm_hr) * 0.04) + (float(tide_m) * 0.30)), 2)
        freeboard = round(max(0.10, 5.00 - drain_depth), 2)
        vel = round(min(4.00, 0.90 + (float(rain_mm_hr) * 0.02)), 2)

        return {
            "device_uid": "MUM_BMC_SCADA_DR_084",
            "municipality": "Brihanmumbai Municipal Corporation",
            "drain_network": "BRIMSTOWAD_MITHI_CATCHMENT",
            "sub_station": "Kurla_Krantinagar_Culvert",
            "coordinates": {"latitude": 19.0684, "longitude": 72.8856},
            "timestamp_epoch_ms": int(time.time() * 1000),
            "metrics": {
                "water_stage_depth_m": drain_depth,
                "freeboard_clearance_m": freeboard,
                "silt_deposition_estimate_m": 0.45,
                "flow_velocity_radar_m_s": vel,
                "sea_tide_height_m_chart_datum": float(tide_m)
            },
            "pumping_stations": self.pumps,
            "status": "OVERFLOW_RISK" if freeboard < 0.50 else "OPERATIONAL"
        }


# Performs basic rainfall, temporal, and spatial quality checks.
class MultiStageQCEngine:
    def __init__(self):
        self.stage_history = {}

    def check_rainfall(self, rain_mm_hr: float) -> tuple:
        if rain_mm_hr is None or rain_mm_hr < 0:
            return False, "Rainfall rate cannot be negative"
        # Reject rainfall values above the configured upper sanity-check limit.
        if rain_mm_hr > 350.0:
            return False, "Reading exceeds Indian record physical limit (>350 mm/hr)"
        return True, "Valid rainfall observation"

    def check_stage(self, station: str, stage_m: float, hfl_m: float = 5.42) -> tuple:
        if stage_m < 0 or stage_m > (hfl_m + 4.0):
            return False, f"Stage {stage_m}m outside realistic channel limits"

        t_now = time.time()
        readings = self.stage_history.setdefault(station, [])
        readings.append({"time": t_now, "val": stage_m})
        if len(readings) > 12:
            readings.pop(0)

        # Look for an unusually fast change between consecutive readings.
        if len(readings) >= 2:
            dt_hr = max(0.001, (t_now - readings[-2]["time"]) / 3600.0)
            dh_dt = abs(stage_m - readings[-2]["val"]) / dt_hr
            if dh_dt > 4.0:
                return False, f"Rate of rise spike anomaly: {dh_dt:.2f} m/hr exceeds 4.0 m/hr limit"

        # Look for a sensor that has reported essentially the same value repeatedly.
        if len(readings) >= 5:
            vals = [pt["val"] for pt in readings]
            mu = sum(vals) / len(vals)
            variance = sum((v - mu) ** 2 for v in vals) / len(vals)
            if variance < 0.0001 and max(vals) != 0.0:
                return False, "Stuck sensor detected: zero variance across 5 consecutive readings"

        return True, "Sensor passed temporal QC checks"

    def check_spatial_zscore(self, value: float, neighbors: list) -> tuple:
        # Compare the reading with nearby stations when enough neighbors are available.
        if not neighbors or len(neighbors) < 2:
            return True, "Insufficient neighboring nodes for spatial Z-score"

        avg_val = sum(neighbors) / len(neighbors)
        variance = sum((x - avg_val) ** 2 for x in neighbors) / len(neighbors)
        std_dev = math.sqrt(variance)

        if std_dev < 1e-3:
            return True, "All neighboring stations report identical stage"

        z_score = abs(value - avg_val) / std_dev
        if z_score > 3.5:
            return False, f"Spatial anomaly detected: Z-score is {z_score:.2f} (> 3.5 threshold)"
        return True, f"Spatial check passed (Z-score: {z_score:.2f})"


# Provides backup data sources if the primary AWS feed is unavailable.
class FallbackHierarchyEngine:
    TIERS = [
        {"tier": 0, "name": "IMD Automatic Weather Station (AWS)", "status": "ACTIVE"},
        {"tier": 1, "name": "IMD Doppler Weather Radar (DWR)", "status": "STANDBY"},
        {"tier": 2, "name": "ISRO MOSDAC INSAT-3DR HEM Satellite", "status": "STANDBY"},
        {"tier": 3, "name": "IMD WRF Numerical Forecast Grid (3km)", "status": "STANDBY"},
        {"tier": 4, "name": "Climatological Historical Persistence", "status": "STANDBY"}
    ]

    def __init__(self):
        self.active_tier = 0

    def set_tier(self, tier_idx: int) -> dict:
        if 0 <= tier_idx < len(self.TIERS):
            self.active_tier = tier_idx
            for idx, entry in enumerate(self.TIERS):
                entry["status"] = "ACTIVE" if idx == tier_idx else "STANDBY"
            log.info(f"Switched data pipeline source to Tier {tier_idx}: {self.TIERS[tier_idx]['name']}")
        return self.get_status()

    def get_status(self) -> dict:
        return {
            "active_tier": self.active_tier,
            "active_source": self.TIERS[self.active_tier]["name"],
            "failover_active": self.active_tier > 0,
            "tiers": self.TIERS
        }
