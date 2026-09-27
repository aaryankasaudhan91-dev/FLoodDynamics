import time
from fastapi.testclient import TestClient
from main import app
from engine.telemetry import (
    CWCIndiaWRISEngine,
    IMDWeatherEngine,
    ISROBhuvanSpatialEngine,
    SurveyOfIndiaCORSEngine,
    ISROMOSDACPrecipEngine,
    MunicipalSCADAEngine,
    MultiStageQCEngine,
    FallbackHierarchyEngine
)

def run_tests():
    print("Running FloodGuard Phase 1 Test Suite...\n")
    client = TestClient(app)

    # 1. CWC river stage & Vihar reservoir discharge tests
    cwc = CWCIndiaWRISEngine()
    q_calc = cwc.compute_discharge(stage=3.0, h_0=0.85, c_r=48.5, beta=1.68)
    assert q_calc > 0, "Rating curve discharge should be positive for stage > h_0"
    print(f"[PASS] CWC rating curve: stage 3.0m -> {q_calc} cumecs")

    res_cwc = client.get("/api/v1/cwc/telemetry?station=CWC_GAUGE_MITHI_01")
    assert res_cwc.status_code == 200
    stn_data = res_cwc.json()
    assert "hydrological_data" in stn_data
    print(f"[PASS] /api/v1/cwc/telemetry: {stn_data['station_name']} stage={stn_data['hydrological_data']['water_level_m_msl']}m")

    r_lake = client.get("/api/v1/cwc/reservoir?code=RES_VIHAR_MUMBAI")
    assert r_lake.status_code == 200
    vihar_data = r_lake.json()
    assert "storage_metrics" in vihar_data
    print(f"[PASS] /api/v1/cwc/reservoir: {vihar_data['name']} level={vihar_data['storage_metrics']['current_water_level_m']}m")

    # 2. IMD Radar Marshall-Palmer & Clutter Filter
    imd = IMDWeatherEngine()
    rain_rate = imd.marshall_palmer_inversion(dbz=42.0, regime="convective")
    assert rain_rate > 0
    print(f"[PASS] IMD Marshall-Palmer: 42 dBZ convective -> {rain_rate} mm/hr")

    is_clutter, reason = imd.is_ground_clutter(dbz=45.0, velocity_m_s=0.05)
    assert is_clutter is True
    print(f"[PASS] IMD ground clutter filter: stationary obstacle correctly identified")

    r_radar = client.post("/api/v1/imd/radar-transform", json={"dbz": 38.0, "regime": "stratiform"})
    assert r_radar.status_code == 200
    print(f"[PASS] /api/v1/imd/radar-transform: 38 dBZ stratiform -> {r_radar.json()['rain_rate_mm_hr']} mm/hr")

    # 3. IMD NOWCAST Alert
    r_nc = client.get("/api/v1/imd/nowcast")
    assert r_nc.status_code == 200
    nc = r_nc.json()
    assert "affected_region" in nc
    print(f"[PASS] /api/v1/imd/nowcast: {nc['identifier']} severity={nc['severity']}")

    # 4. ISRO Bhuvan Hydro-Conditioning (Sink Filling & Stream Burning)
    bhuvan = ISROBhuvanSpatialEngine()
    test_grid = [
        [10.0, 10.0, 10.0],
        [10.0,  5.0, 10.0],
        [10.0, 10.0, 10.0]
    ]
    cond = bhuvan.hydro_condition(test_grid)
    assert cond["sinks_filled"] == 1
    assert cond["output_grid"][1][1] == 10.0
    print(f"[PASS] ISRO Bhuvan depression filling: sink at (1,1) raised to 10.0m")

    # 5. Survey of India CORS Calibration
    soi = SurveyOfIndiaCORSEngine()
    h_ortho = soi.calibrate_height(10.0)
    assert abs(h_ortho - (10.0 - (-42.85))) < 0.01
    print(f"[PASS] SoI CORS: h_wgs84 10.0m calibrated to {h_ortho}m orthometric")

    # 6. ISRO MOSDAC Satellite Ingestion
    mosdac = ISROMOSDACPrecipEngine()
    assert mosdac.clean_rain_rate(-999.0) == 0.0
    assert mosdac.clean_rain_rate(450.0) == 300.0
    print(f"[PASS] ISRO MOSDAC: -999 nodata and extreme cap (>300 mm/hr) verified")

    # 7. Municipal SCADA (BMC BRIMSTOWAD)
    r_scada = client.get("/api/v1/scada/brimstowad")
    assert r_scada.status_code == 200
    scada_data = r_scada.json()
    assert "metrics" in scada_data
    assert "pumping_stations" in scada_data
    print(f"[PASS] BMC SCADA: Kurla culvert depth={scada_data['metrics']['water_stage_depth_m']}m, freeboard={scada_data['metrics']['freeboard_clearance_m']}m")

    # 8. 3-Stage Quality Control
    qc = MultiStageQCEngine()
    valid, msg = qc.check_rainfall(65.0)
    assert valid is True
    valid_bad, msg_bad = qc.check_rainfall(-5.0)
    assert valid_bad is False
    print(f"[PASS] QC Stage 1: rainfall limits check verified")

    # Stage 2: Spike detection (5m rise in 5 minutes = 60 m/hr -> exceeds 4.0 m/hr threshold)
    qc.stage_history["TEST_STATION"] = [{"time": time.time() - 300, "val": 2.0}]
    valid_spike, spike_msg = qc.check_stage("TEST_STATION", 7.0)
    assert valid_spike is False
    print(f"[PASS] QC Stage 2: rapid telemetry spike flagged successfully")

    # Stage 3: Spatial Z-score
    valid_spatial, z_msg = qc.check_spatial_zscore(5.0, [2.0, 2.1, 2.05])
    assert valid_spatial is False
    print(f"[PASS] QC Stage 3: spatial anomaly flagged (outlier vs neighbors)")

    # 9. Fallback Hierarchy
    r_pipe = client.get("/api/v1/pipeline/status")
    assert r_pipe.status_code == 200
    print(f"[PASS] /api/v1/pipeline/status: active tier = {r_pipe.json()['fallback']['active_source']}")

    r_switch = client.post("/api/v1/pipeline/fallback-tier", json={"tier": 1})
    assert r_switch.status_code == 200
    assert r_switch.json()["active_tier"] == 1
    print(f"[PASS] Fallback switch: active source switched to {r_switch.json()['active_source']}")

    # Reset back to Tier 0
    client.post("/api/v1/pipeline/fallback-tier", json={"tier": 0})

    print("\nAll Phase 1 tests passed successfully!")

if __name__ == "__main__":
    run_tests()
