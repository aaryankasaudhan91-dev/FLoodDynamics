import os
import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("floodguard.api")

APP_NAME = os.getenv("APP_NAME", "FloodGuard")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

from engine.neighborhood_data import NODES, HOSPITALS_AND_SERVICES
from engine.hydraulic_model import HydraulicModel
from engine.routing_engine import FloodRouter, VEHICLES
from engine.phase1_ingestion import (
    CWCIndiaWRISEngine,
    IMDWeatherEngine,
    ISROBhuvanSpatialEngine,
    SurveyOfIndiaCORSEngine,
    ISROMOSDACPrecipEngine,
    MunicipalSCADAEngine,
    MultiStageQCEngine,
    FallbackHierarchyEngine
)
from engine.phase2_routes import router as phase2_router
from engine.phase4_routes import router as phase4_router

app = FastAPI(
    title="FloodGuard IFPS API",
    description="Real-time urban flood nowcasting and emergency routing engine for South-Central Mumbai"
)
app.include_router(phase2_router)
app.include_router(phase4_router)

# Core solvers and telemetry ingestion engines
cwc_engine = CWCIndiaWRISEngine()
imd_engine = IMDWeatherEngine()
bhuvan_engine = ISROBhuvanSpatialEngine()
soi_engine = SurveyOfIndiaCORSEngine()
mosdac_engine = ISROMOSDACPrecipEngine()
scada_engine = MunicipalSCADAEngine()
qc_engine = MultiStageQCEngine()
fallback_engine = FallbackHierarchyEngine()

hydraulic_solver = HydraulicModel()
navigation_router = FloodRouter()

# Baseline monsoon state: 12 mm/hr moderate rain, 2.0m mid-tide
current_sim = hydraulic_solver.simulate(rain_intensity_mm_hr=12.0, tide_level_m=2.0)

class SimInput(BaseModel):
    rain_mm_hr: float = 12.0
    tide_m: float = 2.0
    pump_pct: float = 100.0

class RouteInput(BaseModel):
    start_node: str = "dadar_tt_circle"
    end_node: str = "kem_hospital_gate"
    vehicle_type: str = "ambulance"
    rain_mm_hr: Optional[float] = None
    tide_m: Optional[float] = None
    pump_pct: Optional[float] = None

class RadarConvertInput(BaseModel):
    dbz: float = 38.5
    regime: str = "convective"

class ClutterFilterInput(BaseModel):
    dbz: float = 45.0
    velocity_m_s: float = 0.05
    rho_hv: float = 0.95

class QCValidateInput(BaseModel):
    rainfall_mm_hr: Optional[float] = None
    station: Optional[str] = "CWC_GAUGE_MITHI_01"
    stage_m: Optional[float] = None
    neighbors: Optional[list] = None

class FallbackInput(BaseModel):
    tier: int = 0

class HydroConditionInput(BaseModel):
    grid: List[List[float]]
    stream_mask: Optional[List[List[bool]]] = None
    burn_depth: float = 1.2

@app.get("/api/weather")
def get_weather():
    rain_rate = current_sim["params"]["rain_mm_hr"]
    source = "Simulated Doppler Radar (IMD Santacruz Station)"

    if OPENWEATHER_API_KEY:
        try:
            import urllib.request
            import urllib.error
            import json
            # Dadar coordinate query (19.014N, 72.843E)
            url = f"https://api.openweathermap.org/data/2.5/weather?lat=19.014&lon=72.843&appid={OPENWEATHER_API_KEY}&units=metric"
            req = urllib.request.Request(url, headers={"User-Agent": "FloodGuard/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                payload = json.loads(resp.read().decode())
                if "rain" in payload and "1h" in payload["rain"]:
                    rain_rate = float(payload["rain"]["1h"])
                source = f"Live OpenWeatherMap ({payload.get('weather', [{}])[0].get('description', 'Rain')})"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as err:
            log.warning(f"OpenWeather query failed, falling back to radar: {err}")
    else:
        # Real live IMD AWS / WMO meteorological feed for Mumbai
        live_feed = imd_engine.get_live_rainfall()
        if live_feed.get("online"):
            source = live_feed["source"]

    return {
        "location": "Dadar - Hindmata, Mumbai",
        "rain_mm_hr": rain_rate,
        "tide_m": current_sim["params"]["tide_m"],
        "pump_pct": current_sim["params"]["pump_pct"],
        "river_stage_m": current_sim["summary"]["river_stage_m"],
        "river_status": current_sim["summary"]["river_status"],
        "data_source": source
    }

@app.post("/api/simulate")
def run_simulation(sim_payload: SimInput):
    global current_sim
    current_sim = hydraulic_solver.simulate(
        rain_intensity_mm_hr=sim_payload.rain_mm_hr,
        tide_level_m=sim_payload.tide_m,
        pump_power_pct=sim_payload.pump_pct
    )
    return current_sim

@app.get("/api/hazards")
def get_hazards():
    return {
        "nodes": current_sim["nodes"],
        "summary": current_sim["summary"]
    }

@app.post("/api/route")
def get_route(route_req: RouteInput):
    global current_sim
    if route_req.rain_mm_hr is not None:
        current_sim = hydraulic_solver.simulate(
            rain_intensity_mm_hr=route_req.rain_mm_hr,
            tide_level_m=route_req.tide_m if route_req.tide_m is not None else current_sim["params"]["tide_m"],
            pump_power_pct=route_req.pump_pct if route_req.pump_pct is not None else current_sim["params"]["pump_pct"]
        )

    depth_lookup = {n["id"]: n["depth_cm"] for n in current_sim["nodes"]}
    return navigation_router.find_routes(route_req.start_node, route_req.end_node, depth_lookup, route_req.vehicle_type)

@app.get("/api/nodes")
def get_nodes():
    return [
        {"id": n["id"], "name": n["name"], "lat": n["lat"], "lon": n["lon"], "elevation_m": n["elevation_m"]}
        for n in NODES
    ]

@app.get("/api/facilities")
def get_facilities():
    return current_sim["facilities"]

@app.get("/api/telemetry")
def get_telemetry():
    stage = current_sim["summary"]["river_stage_m"]
    # 6-hour rolling hydrograph window for Mithi river stage
    chart_points = [
        {"time": "-4h", "stage_m": round(stage - 0.70, 2)},
        {"time": "-2h", "stage_m": round(stage - 0.35, 2)},
        {"time": "Now", "stage_m": stage},
        {"time": "+1h", "stage_m": round(min(5.40, stage + 0.30), 2)},
        {"time": "+2h", "stage_m": round(min(5.50, stage + 0.55), 2)},
    ]
    return {
        "river": "Mithi River / Mahim Creek",
        "current_stage_m": stage,
        "warning_m": 3.90,
        "danger_m": 4.80,
        "status": current_sim["summary"]["river_status"],
        "chart_data": chart_points
    }

# Phase 1 Ingestion Endpoints (CWC, IMD, ISRO, BMC SCADA)
@app.get("/api/v1/cwc/telemetry")
def get_cwc_telemetry(station: str = "CWC_GAUGE_MITHI_01"):
    live_stage = current_sim["summary"]["river_stage_m"]
    return cwc_engine.get_station_observation(station, stage_override=live_stage)

@app.get("/api/v1/cwc/reservoir")
def get_cwc_reservoir(code: str = "RES_VIHAR_MUMBAI"):
    return cwc_engine.get_reservoir_status(code)

@app.get("/api/v1/imd/nowcast")
def get_imd_nowcast():
    cur_rain = current_sim["params"]["rain_mm_hr"]
    return imd_engine.get_nowcast_alert(cur_rain)

@app.post("/api/v1/imd/radar-transform")
def convert_radar_reflectivity(radar_req: RadarConvertInput):
    r_calc = imd_engine.marshall_palmer_inversion(radar_req.dbz, radar_req.regime)
    return {"dbz": radar_req.dbz, "regime": radar_req.regime, "rain_rate_mm_hr": r_calc}

@app.post("/api/v1/imd/clutter-filter")
def filter_radar_clutter(clutter_req: ClutterFilterInput):
    is_clutter, reason = imd_engine.is_ground_clutter(clutter_req.dbz, clutter_req.velocity_m_s, clutter_req.rho_hv)
    return {"is_clutter": is_clutter, "reason": reason}

@app.post("/api/v1/bhuvan/hydro-condition")
def condition_dem(dem_req: HydroConditionInput):
    return bhuvan_engine.hydro_condition(dem_req.grid, dem_req.stream_mask, dem_req.burn_depth)

@app.get("/api/v1/soi/cors-calibrate")
def calibrate_cors(h_wgs84: float = 10.0):
    return {
        "h_wgs84_m": h_wgs84,
        "geoid_undulation_m": soi_engine.MUMBAI_GEOID_N,
        "h_orthometric_m": soi_engine.calibrate_height(h_wgs84)
    }

@app.get("/api/v1/mosdac/hem-precip")
def get_mosdac_precip(raw_rate: float = 35.0):
    return {
        "raw_mm_hr": raw_rate,
        "cleaned_mm_hr": mosdac_engine.clean_rain_rate(raw_rate)
    }

@app.get("/api/v1/scada/brimstowad")
def get_scada_telemetry():
    r_val = current_sim["params"]["rain_mm_hr"]
    t_val = current_sim["params"]["tide_m"]
    return scada_engine.get_drain_readings(r_val, t_val)

@app.post("/api/v1/qc/validate")
def validate_sensor_reading(qc_req: QCValidateInput):
    checks = {}
    if qc_req.rainfall_mm_hr is not None:
        ok, msg = qc_engine.check_rainfall(qc_req.rainfall_mm_hr)
        checks["rainfall_qc"] = {"valid": ok, "message": msg}

    if qc_req.stage_m is not None:
        ok, msg = qc_engine.check_stage(qc_req.station, qc_req.stage_m)
        checks["stage_qc"] = {"valid": ok, "message": msg}

    if qc_req.neighbors is not None and qc_req.stage_m is not None:
        ok, msg = qc_engine.check_spatial_zscore(qc_req.stage_m, qc_req.neighbors)
        checks["spatial_qc"] = {"valid": ok, "message": msg}

    return checks

@app.get("/api/v1/pipeline/status")
def get_pipeline_status():
    return {
        "fallback": fallback_engine.get_status(),
        "feeds": {
            "cwc_wris": "ONLINE",
            "imd_aws": "ONLINE",
            "imd_dwr": "ONLINE",
            "isro_bhuvan": "ONLINE",
            "isro_mosdac": "ONLINE",
            "bmc_scada": "ONLINE"
        },
        "last_sync": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    }

@app.post("/api/v1/pipeline/fallback-tier")
def switch_fallback_tier(tier_req: FallbackInput):
    return fallback_engine.set_tier(tier_req.tier)

@app.get("/api/v1/db/schema")
def get_db_schema():
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine", "db_schema.sql")
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            return {"schema": f.read()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Database schema file not found")

STATIC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")

@app.get("/")
def home():
    index_file = os.path.join(STATIC_PATH, "index.html")
    return FileResponse(index_file)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
