## Detection Result 

# Likelihood of Al Generation: 88% 



<!-- Start of picture text -->
°<br>88%<br><!-- End of picture text -->

The code exhibits multiple hallmarks of Al-generated code, including consistent naming conventions, lack of context-specific comments, perfectly structured code style, generic helper functions, and absence of specialized business logic, so it is highly likely Al-generated. 

Naming Style: Class, method, and variable names follow a highly consistent camelCase and UpperCamelCase convention, lacking business-specific abbreviations or personal naming variations. 

Comment Style: There are virtually no comments throughout the entire code, which is typical for Al-generated code that focuses on clean structure over contextual explanations. 

Code Structure: Code is uniformly formatted with consistent indentations and style, clear separation of concerns, and no syntactic or structural errors, suggesting automated generation. 

Typical Al Traits: Multiple helper methods with generic names, like compute_discharge and check_stage, and repetitive patterns such as default parameter usage and defensive coding without deep exception handling reflect typical Al-generated patterns. 

Business Footprints Missing: The code uses plausible but generic placeholder values and hard-coded example datasets with no integration of real-time or complex business logic, indicating lack of true domain customization. 

```
import math
```

```
import time
```

```
from datetime import datetime, timezone
```

```
class CWCIndiaWRISEngine:
```

```
    def __init__(self):
```

```
        self.stations = {
            "CWC_GAUGE_MITHI_01": {
```

```
                "name": "Mithi River - Kurla Station",
                "lat": 19.0684,
                "lon": 72.8856,
                "elevation": 3.2,
                "h_0": 0.85,
                "c_r": 48.5,
                "beta": 1.68,
```

```
                "warning_level": 3.90,
```

```
                "danger_level": 4.80,
```

```
                "hfl": 5.42,
```

```
                "current_stage": 2.15,
```

```
                "prev_stage": 2.10,
```

```
                "prev_time": time.time() - 900
```

```
            },
```

```
            "CWC_GAUGE_MAHIM_02": {
```

```
                "name": "Mahim Creek Outfall",
```

```
                "lat": 19.0410,
```

```
                "lon": 72.8420,
```

```
                "elevation": 1.5,
```

```
                "h_0": 0.20,
                "c_r": 55.0,
```

```
                "beta": 1.72,
```

```
                "warning_level": 3.20,
```

```
                "danger_level": 4.10,
```

```
                "hfl": 4.85,
```

```
                "current_stage": 1.65,
```

```
                "prev_stage": 1.60,
```

```
                "prev_time": time.time() - 900
```

```
            }
```

```
        }
```

```
        self.reservoirs = {
```

```
            "RES_VIHAR_MUMBAI": {
```

```
                "name": "Vihar Lake",
                "frl": 80.42,
                "mwl": 81.10,
                "current_level": 79.15,
                "gross_storage_bcm": 0.091,
                "live_storage_bcm": 0.082,
                "utilization_pct": 90.1,
                "inflow_cumecs": 142.0,
```

```
                "outflow_cumecs": 35.0
```

```
            },
```

```
            "RES_TULSI_MUMBAI": {
```

```
                "name": "Tulsi Lake",
```

```
                "frl": 139.17,
                "mwl": 139.60,
                "current_level": 138.80,
```

```
                "gross_storage_bcm": 0.024,
```

```
                "live_storage_bcm": 0.021,
```

```
                "utilization_pct": 87.5,
```

```
                "inflow_cumecs": 45.0,
```

```
                "outflow_cumecs": 12.0
            }
        }
```

```
    def compute_discharge(self, stage: float, h_0: float, c_r: float, beta: float) -> float:
```

```
        head = max(0.0, stage - h_0)
```

```
        if head <= 0:
```

```
            return 0.0
```

```
        return round(c_r * (head ** beta), 2)
```

```
    def get_station_observation(self, station_code: str = "CWC_GAUGE_MITHI_01", stage_override: float = None) -> dict:
```

```
        st = self.stations.get(station_code, self.stations["CWC_GAUGE_MITHI_01"])
```

```
        stage = stage_override if stage_override is not None else st["current_stage"]
```

```
        discharge = self.compute_discharge(stage, st["h_0"], st["c_r"], st["beta"])
```

```
        now = time.time()
```

```
        dt_hr = max(0.01, (now - st["prev_time"]) / 3600.0)
```

```
        rate_of_rise = round((stage - st["prev_stage"]) / dt_hr, 2)
```

```
        return {
```

```
            "agency": "CWC",
            "basin_code": "CWC_BASIN_MITHI_01",
            "sub_basin": "Mithi_Estuary",
            "station_code": station_code,
            "station_name": st["name"],
```

```
            "geo_coordinates": {
                "latitude": st["lat"],
                "longitude": st["lon"],
                "elevation_m_msl": st["elevation"]
            },
```

```
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
```

```
            "telemetry_type": "RADAR_LEVEL_SENSOR",
```

```
            "hydrological_data": {
                "water_level_m_msl": round(stage, 2),
```

```
                "discharge_cumecs": discharge,
```

```
                "rate_of_rise_m_per_hr": rate_of_rise,
```

```
                "warning_level_m_msl": st["warning_level"],
```

```
                "danger_level_m_msl": st["danger_level"],
```

```
                "highest_flood_level_hfl": {
```

```
                    "level_m_msl": st["hfl"],
```

```
                    "recorded_date": "2005-07-26"
```

```
                }
```

```
            },
```

```
            "qc_flags": {
```

```
                "sensor_health": "NOMINAL",
```

```
                "battery_volts": 12.6,
```

```
                "acoustic_confidence_pct": 98
```

```
            },
```

```
            "status": "DANGER" if stage >= st["danger_level"] else ("WARNING" if stage >= st["warning_level"] else "NORMAL")
```

```
        }
```

```
    def get_reservoir_status(self, code: str = "RES_VIHAR_MUMBAI") -> dict:
```

```
        res = self.reservoirs.get(code, self.reservoirs["RES_VIHAR_MUMBAI"])
```

```
        return {
```

```
            "agency": "CWC",
```

```
            "reservoir_code": code,
```

```
            "name": res["name"],
```

```
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
```

```
            "storage_metrics": {
```

```
                "full_reservoir_level_frl_m": res["frl"],
```

```
                "maximum_water_level_mwl_m": res["mwl"],
```

```
                "current_water_level_m": res["current_level"],
```

```
                "gross_storage_capacity_bcm": res["gross_storage_bcm"],
```

```
                "current_live_storage_bcm": res["live_storage_bcm"],
```

```
                "storage_capacity_utilization_pct": res["utilization_pct"],
```

```
                "inflow_cumecs": res["inflow_cumecs"],
```

```
                "spillway_outflow_cumecs": res["outflow_cumecs"]
```

```
            }
```

```
        }
```

```
class IMDWeatherEngine:
```

```
    REGIMES = {
```

```
        "stratiform": {"a": 200.0, "b": 1.60},
```

```
        "convective": {"a": 300.0, "b": 1.40},
```

```
        "cyclonic":   {"a": 150.0, "b": 1.80}
```

```
    }
```

```
    def marshall_palmer_inversion(self, dbz: float, regime: str = "convective") -> float:
```

```
        if dbz <= 12.0:
```

```
            return 0.0
```

```
        p = self.REGIMES.get(regime, self.REGIMES["convective"])
```

```
        z_linear = 10.0 ** (dbz / 10.0)
```

```
        rain_rate = (z_linear / p["a"]) ** (1.0 / p["b"])
```

```
        return round(float(rain_rate), 2)
```

```
    def is_ground_clutter(self, dbz: float, velocity_m_s: float, rho_hv: float = 0.95) -> tuple:
```

```
        if abs(velocity_m_s) < 0.2 and dbz > 40.0:
```

```
            return True, "Doppler velocity near 0 with high dBZ suggests ground clutter"
```

```
        if rho_hv < 0.85:
```

```
            return True, "Dual-pol RhoHV < 0.85 indicates non-weather echo"
```

```
        return False, "Echo appears to be real precipitation"
```

```
    def polar_to_cartesian(self, range_km: float, azimuth_deg: float, elevation_deg: float = 0.5) -> tuple:
```

```
        r = range_km * 1000.0
```

```
        theta = math.radians(elevation_deg)
```

```
        phi = math.radians(azimuth_deg)
```

```
        k_e = 4.0 / 3.0
```

```
        r_earth = 6371000.0
```

```
        x = r * math.cos(theta) * math.sin(phi)
```

```
        y = r * math.cos(theta) * math.cos(phi)
```

```
        z = 45.0 + (r * math.sin(theta)) + ((r ** 2) / (2.0 * k_e * r_earth))
```

```
        return round(x, 1), round(y, 1), round(z, 1)
```

```
    def get_nowcast_alert(self, current_rain_rate: float) -> dict:
```

```
        now = datetime.now(timezone.utc)
```

```
        is_severe = current_rain_rate >= 45.0
```

```
        return {
```

```
            "alert_type": "IMD_NOWCAST_FLASH_FLOOD",
```

```
            "identifier": f"IMD-NC-{now.strftime('%Y%m%d')}-MH-MUM-001",
```

```
            "sent_time_utc": now.isoformat(),
```

```
            "valid_until_utc": datetime.fromtimestamp(now.timestamp() + 10800, timezone.utc).isoformat(),
```

```
            "severity": "WARNING" if is_severe else "ADVISORY",
```

```
            "certainty": "VERY_LIKELY" if is_severe else "POSSIBLE",
```

```
            "affected_region": {
```

```
                "state": "Maharashtra",
```

```
                "district": "Mumbai Suburban",
```

```
                "basin": "Dadar - Hindmata Urban Catchment",
```

```
                "coordinates": [
```

```
                    [19.005, 72.835], [19.025, 72.835],
```

```
                    [19.025, 72.855], [19.005, 72.855], [19.005, 72.835]
```

```
                ]
```

```
            },
```

```
            "quantitative_forecast": {
```

```
                "expected_rainfall_3hr_mm": round(current_rain_rate * 2.8, 1),
```

```
                "surface_wind_gust_kmph": 65.0 if is_severe else 25.0,
```

```
                "hazard_profile": "URBAN_FLASH_FLOOD_LOW_LYING_WATERLOGGING"
```

```
            }
```

```
        }
```

```
class ISROBhuvanSpatialEngine:
```

```
    def hydro_condition(self, grid: list, stream_mask: list = None, burn_depth: float = 1.2) -> dict:
```

```
        rows = len(grid)
```

```
        cols = len(grid[0]) if rows > 0 else 0
```

```
        conditioned = [row[:] for row in grid]
```

```
        sinks_filled = 0
```

```
        for r in range(1, rows - 1):
```

```
            for c in range(1, cols - 1):
```

```
                neighbors = [
```

```
                    conditioned[r-1][c], conditioned[r+1][c],
```

```
                    conditioned[r][c-1], conditioned[r][c+1]
```

```
                ]
```

```
                min_n = min(neighbors)
```

```
                if conditioned[r][c] < min_n:
```

```
                    conditioned[r][c] = min_n
```

```
                    sinks_filled += 1
```

```
        streams_burned = 0
```

```
        if stream_mask:
```

```
            for r in range(rows):
```

```
                for c in range(cols):
```

```
                    if stream_mask[r][c]:
```

```
                        conditioned[r][c] = round(conditioned[r][c] - burn_depth, 2)
```

```
                        streams_burned += 1
```

```
        return {
```

```
            "grid_size": f"{rows}x{cols}",
```

```
            "sinks_filled": sinks_filled,
```

```
            "streams_burned": streams_burned,
```

```
            "burn_depth_m": burn_depth,
```

```
            "output_grid": conditioned
```

```
        }
```

```
class SurveyOfIndiaCORSEngine:
```

```
    MUMBAI_GEOID_N = -42.85
```

```
    def calibrate_height(self, h_wgs84: float) -> float:
```

```
        return round(h_wgs84 - self.MUMBAI_GEOID_N, 3)
```

```
class ISROMOSDACPrecipEngine:
```

```
    def clean_rain_rate(self, raw_rate: float) -> float:
```

```
        if raw_rate is None or math.isnan(raw_rate) or raw_rate < 0 or raw_rate == -999.0:
```

```
            return 0.0
```

```
        return min(300.0, round(raw_rate, 2))
```

```
class MunicipalSCADAEngine:
```

```
    def __init__(self):
```

```
        self.pumps = {
```

```
            "Britannia": {"capacity_cumecs": 36.0, "active": 6, "total": 6, "status": "RUNNING"},
```

```
            "Lovegrove": {"capacity_cumecs": 45.0, "active": 8, "total": 8, "status": "RUNNING"},
```

```
            "Cleveland": {"capacity_cumecs": 30.0, "active": 5, "total": 6, "status": "RUNNING"},
```

```
            "Haji Ali":  {"capacity_cumecs": 24.0, "active": 4, "total": 4, "status": "RUNNING"}
```

```
        }
```

```
    def get_drain_readings(self, rain_mm_hr: float = 25.0, tide_m: float = 2.0) -> dict:
```

```
        depth = round(min(5.2, 1.6 + (rain_mm_hr * 0.04) + (tide_m * 0.3)), 2)
```

```
        freeboard = round(max(0.1, 5.0 - depth), 2)
```

```
        velocity = round(min(4.0, 0.9 + (rain_mm_hr * 0.02)), 2)
```

```
        return {
```

```
            "device_uid": "MUM_BMC_SCADA_DR_084",
```

```
            "municipality": "Brihanmumbai Municipal Corporation",
```

```
            "drain_network": "BRIMSTOWAD_MITHI_CATCHMENT",
```

```
            "sub_station": "Kurla_Krantinagar_Culvert",
```

```
            "coordinates": {"latitude": 19.0684, "longitude": 72.8856},
```

```
            "timestamp_epoch_ms": int(time.time() * 1000),
```

```
            "metrics": {
```

```
                "water_stage_depth_m": depth,
```

```
                "freeboard_clearance_m": freeboard,
```

```
                "silt_deposition_estimate_m": 0.45,
```

```
                "flow_velocity_radar_m_s": velocity,
```

```
                "sea_tide_height_m_chart_datum": tide_m
```

```
            },
```

```
            "pumping_stations": self.pumps,
```

```
            "status": "OVERFLOW_RISK" if freeboard < 0.5 else "OPERATIONAL"
```

```
        }
```

```
class MultiStageQCEngine:
```

```
    def __init__(self):
```

```
        self.stage_history = {}
```

```
    def check_rainfall(self, rain_mm_hr: float) -> tuple:
```

```
        if rain_mm_hr < 0:
```

```
            return False, "Rain rate cannot be negative"
```

```
        if rain_mm_hr > 350.0:
```

```
            return False, "Value exceeds physical limit of 350 mm/hr"
```

```
        return True, "Valid rainfall observation"
```

```
    def check_stage(self, station: str, stage_m: float, hfl_m: float = 5.42) -> tuple:
```

```
        if stage_m < 0 or stage_m > (hfl_m + 4.0):
```

```
            return False, f"Stage {stage_m}m outside realistic range"
```

```
        now = time.time()
```

```
        readings = self.stage_history.setdefault(station, [])
```

```
        readings.append({"time": now, "val": stage_m})
```

```
        if len(readings) > 12:
```

```
            readings.pop(0)
```

```
        if len(readings) >= 2:
```

```
            prev = readings[-2]
```

```
            dt_hours = max(0.001, (now - prev["time"]) / 3600.0)
```

```
            dh_dt = abs(stage_m - prev["val"]) / dt_hours
```

```
            if dh_dt > 4.0:
```

```
                return False, f"Spike detected: rate of rise is {dh_dt:.2f} m/hr"
```

```
        if len(readings) >= 5:
```

```
            vals = [r["val"] for r in readings]
```

```
            avg = sum(vals) / len(vals)
```

```
            var = sum((v - avg) ** 2 for v in vals) / len(vals)
```

```
            if var < 0.0001 and max(vals) != 0:
```

```
                return False, "Sensor reading unchanged over multiple intervals, possible stuck sensor"
```

```
        return True, "Passed stage checks"
```

```
    def check_spatial_zscore(self, value: float, neighbors: list) -> tuple:
```

```
        if not neighbors or len(neighbors) < 2:
```

```
            return True, "Need at least 2 neighbors for spatial check"
```

```
        mean = sum(neighbors) / len(neighbors)
```

```
        variance = sum((x - mean) ** 2 for x in neighbors) / len(neighbors)
```

```
        std = math.sqrt(variance)
```

```
        if std < 1e-3:
```

```
            return True, "Neighbor values are identical"
```

```
        z = abs(value - mean) / std
```

```
        if z > 3.5:
```

```
            return False, f"Spatial anomaly detected, z-score is {z:.2f}"
```

```
        return True, f"Spatial check passed (z-score {z:.2f})"
```

```
class FallbackHierarchyEngine:
```

```
    TIERS = [
```

```
        {"tier": 0, "name": "IMD Automatic Weather Station (AWS)", "status": "ACTIVE"},
```

```
        {"tier": 1, "name": "IMD Doppler Weather Radar (DWR)", "status": "STANDBY"},
```

- `{"tier": 2, "name": "ISRO MOSDAC INSAT-3DR HEM Satellite", "status": "STANDBY"}, {"tier": 3, "name": "IMD WRF Numerical Forecast Grid (3km)", "status": "STANDBY"},` 

```
        {"tier": 4, "name": "Climatological Historical Persistence", "status": "STANDBY"}
    ]
```

```
    def __init__(self):
```

```
        self.active_tier = 0
```

```
    def set_tier(self, tier_idx: int) -> dict:
```

```
        if 0 <= tier_idx < len(self.TIERS):
```

```
            self.active_tier = tier_idx
```

```
            for i, t in enumerate(self.TIERS):
```

```
                t["status"] = "ACTIVE" if i == tier_idx else "STANDBY"
```

```
        return self.get_status()
```

```
    def get_status(self) -> dict:
```

```
        return {
```

```
            "active_tier": self.active_tier,
```

```
            "active_source": self.TIERS[self.active_tier]["name"],
```

```
            "failover_active": self.active_tier > 0,
```

```
            "tiers": self.TIERS
```

```
        }
```

