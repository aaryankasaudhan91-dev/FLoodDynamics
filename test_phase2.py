import time
from fastapi.testclient import TestClient
from main import app
from engine.phase2_hydrodynamics import (
    PreissmannSlotPipe,
    Coupled1D2DExchange,
    DynamicRoughnessBlockage,
    EstuarineTidalBoundary,
    HydrographSignalAnalyzer
)

def run_tests():
    print("Running FloodGuard Phase 2 Hydraulic Engine Test Suite...\n")
    client = TestClient(app)

    # 1. Preissmann Slot Conduit Pressurization
    pipe = PreissmannSlotPipe(diameter_m=1.0, slope=0.002, manning_n=0.015)
    
    # 1a. Partially full gravity flow (0.6m in 1.0m pipe)
    partial = pipe.compute_discharge(stage_y=0.6)
    assert not partial["is_pressurized"]
    assert partial["discharge_cumecs"] > 0
    print(f"[PASS] Preissmann gravity flow: y=0.6m in 1.0m pipe -> Q={partial['discharge_cumecs']} m3/s")

    # 1b. Surcharged pressurized flow (1.3m in 1.0m pipe)
    surcharged = pipe.compute_discharge(stage_y=1.3)
    assert surcharged["is_pressurized"]
    assert surcharged["slot_width_m"] > 0
    assert surcharged["wetted_area_sqm"] > pipe.a_full
    print(f"[PASS] Preissmann pressurized slot: y=1.3m -> slot Ts={surcharged['slot_width_m']}m, Q={surcharged['discharge_cumecs']} m3/s")

    # 2. Coupled 1D-2D Manhole Exchange
    coupling = Coupled1D2DExchange(inlet_perimeter_m=2.4, inlet_area_sqm=0.36)

    # 2a. Free weir surface drop
    weir = coupling.compute_exchange(h_2d=0.08, h_1d=4.20, z_ground=4.50)
    assert weir["regime"] == "WEIR_INLET"
    assert weir["exchange_q_cumecs"] > 0
    print(f"[PASS] 1D-2D Weir exchange: h_2d=0.08m -> Q={weir['exchange_q_cumecs']} m3/s (inlet drop)")

    # 2b. Submerged orifice capture
    orifice = coupling.compute_exchange(h_2d=1.20, h_1d=4.20, z_ground=4.50)
    assert orifice["regime"] == "ORIFICE_INLET"
    assert orifice["exchange_q_cumecs"] > weir["exchange_q_cumecs"]
    print(f"[PASS] 1D-2D Orifice intake: h_2d=1.20m -> Q={orifice['exchange_q_cumecs']} m3/s (submerged)")

    # 2c. Upward manhole boiling surcharge (H_1D > surface)
    boiling = coupling.compute_exchange(h_2d=0.10, h_1d=5.30, z_ground=4.50)
    assert boiling["regime"] == "UPWARD_SURCHARGE"
    assert boiling["direction"] == "1D_TO_2D"
    print(f"[PASS] 1D-2D Manhole boiling: H_1D=5.30m > ground=4.60m -> Q_surcharge={boiling['exchange_q_cumecs']} m3/s")

    # 2d. Lateral nallah bank overtopping
    nallah_spill = coupling.lateral_nallah_overtopping(h_nallah=5.20, z_bank=4.80, h_2d=0.05, z_ground=4.40)
    assert nallah_spill["spill_q_cumecs"] > 0
    assert not nallah_spill["submerged"]
    print(f"[PASS] Lateral nallah overtopping: crest excess 0.40m -> Q_spill={nallah_spill['spill_q_cumecs']} m3/s")

    # 3. Dynamic Siltation & Solid Waste Blockage
    blockage_calc = DynamicRoughnessBlockage(base_width_m=3.0, clean_manning_n=0.018)
    blk = blockage_calc.calculate(flow_depth_y=1.0, silt_depth_m=0.30, trash_area_sqm=0.35)
    assert blk["blockage_factor_beta"] > 0.40
    assert blk["effective_manning_n"] > blk["design_manning_n"]
    print(f"[PASS] Dynamic blockage: beta={blk['blockage_factor_beta']}, effective n={blk['effective_manning_n']} (conveyance loss {blk['conveyance_loss_pct']}%)")

    # 4. Estuarine Tidal Boundary & Flap Gates
    tide = EstuarineTidalBoundary()
    twl = tide.compute_twl(hours_from_epoch=6.0, surge_anomaly_m=0.30)
    assert -3.0 <= twl <= 4.5
    print(f"[PASS] Arabian Sea TWL: t=6h -> TWL={twl}m CD (harmonic astronomical tide + surge)")

    # Flap gate locked by high tide
    gate_locked = tide.evaluate_outfall_gate(internal_nallah_head=2.80, twl_ocean=3.90, has_flap_gate=True)
    assert gate_locked["gate_state"] == "LOCKED_SHUT"
    assert gate_locked["discharge_cumecs"] == 0.0
    print(f"[PASS] Tidal flap gate: ocean=3.90m > nallah=2.80m -> Gate LOCKED_SHUT (outflow halted)")

    # 5. In-Situ Signal Analyzer (Rate of Rise & Mass Conservation)
    t_now = time.time()
    series = [
        {"time": t_now - 1800, "stage_m": 2.10},
        {"time": t_now, "stage_m": 4.10}  # 2.0m rise in 30 mins = 4.0 m/hr
    ]
    rise = HydrographSignalAnalyzer.rate_of_rise(series)
    assert rise["is_flash_surge"] is True
    print(f"[PASS] Signal analysis: dh/dt={rise['dh_dt_m_per_hr']} m/hr -> {rise['status']}")

    # Recession tau
    tau = HydrographSignalAnalyzer.calculate_recession_tau(peak_stage=4.80, current_stage=2.40, elapsed_hours=3.5)
    assert 2.0 <= tau <= 8.0
    print(f"[PASS] Hydrograph recession: peak 4.8m -> current 2.4m in 3.5h -> tau={tau} hours")

    # Mass balance audit
    audit = HydrographSignalAnalyzer.mass_balance_rme(inflow_m3=20000.0, outflow_m3=14000.0, storage_change_m3=5950.0)
    assert audit["is_conserved"] is True
    assert audit["rme_percent"] < 1.0
    print(f"[PASS] Mass conservation audit: RME={audit['rme_percent']}% -> {audit['audit_verdict']}")

    # 6. REST API Endpoints Verification
    res_p2 = client.post("/api/v2/hydro/preissmann-conduit", json={"diameter_m": 1.2, "stage_y": 1.5})
    assert res_p2.status_code == 200
    assert res_p2.json()["is_pressurized"] is True
    print(f"[PASS] /api/v2/hydro/preissmann-conduit: Q={res_p2.json()['discharge_cumecs']} m3/s")

    res_tide = client.post("/api/v2/hydro/tidal-boundary", json={"hours_from_epoch": 12.0, "internal_nallah_head": 2.5})
    assert res_tide.status_code == 200
    assert "ocean_twl_m" in res_tide.json()
    print(f"[PASS] /api/v2/hydro/tidal-boundary: TWL={res_tide.json()['ocean_twl_m']}m, gate={res_tide.json()['outfall_gate']['gate_state']}")

    # Full coupled simulation check
    res_sim = client.post("/api/simulate", json={"rain_mm_hr": 45.0, "tide_m": 3.8, "pump_pct": 50.0})
    assert res_sim.status_code == 200
    sim_data = res_sim.json()
    assert "phase2_diagnostics" in sim_data
    assert sim_data["summary"]["mass_balance_conserved"] is True
    print(f"[PASS] /api/simulate with Phase 2 hydrodynamics: RME={sim_data['summary']['mass_balance_rme_pct']}%, flooded={sim_data['summary']['flooded_nodes']} nodes")

    print("\nAll Phase 2 Hydraulic Engine tests passed successfully!")

if __name__ == "__main__":
    run_tests()
