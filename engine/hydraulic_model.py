import math
from typing import Dict, Any, List
from .neighborhood_data import NODES, HOSPITALS_AND_SERVICES
from .phase2_hydrodynamics import (
    PreissmannSlotPipe,
    Coupled1D2DExchange,
    DynamicRoughnessBlockage,
    EstuarineTidalBoundary,
    HydrographSignalAnalyzer
)

# Dadar-Hindmata coupled 1D-2D hydrodynamic solver (Phase 2).
# Incorporates Preissmann slot conduit pressurization, manhole exchange
# (weir / orifice / boiling pop-up), dynamic silt & trash roughness,
# and estuarine tidal backwater flap-gate mechanics.
class HydraulicModel:
    def __init__(self):
        self.nodes = {n["id"]: dict(n) for n in NODES}
        self.services = [dict(s) for s in HOSPITALS_AND_SERVICES]
        self.tidal_engine = EstuarineTidalBoundary()
        self.exchange_engine = Coupled1D2DExchange()
        self.blockage_engine = DynamicRoughnessBlockage()

    def simulate(self, rain_intensity_mm_hr: float = 15.0, tide_level_m: float = 2.0, pump_power_pct: float = 100.0, duration_mins: float = 25.0) -> Dict[str, Any]:
        # 1. Coastal boundary condition (Arabian Sea Mahim Creek outfall)
        twl_ocean = float(tide_level_m)
        is_high_tide = twl_ocean > 3.5 # Spring high tide threshold above Chart Datum
        tide_gate_result = self.tidal_engine.evaluate_outfall_gate(
            internal_nallah_head=3.20,
            twl_ocean=twl_ocean,
            gate_area_sqm=6.0,
            has_flap_gate=True
        )

        pump_factor = max(0.10, pump_power_pct / 100.0)
        storm_duration_sec = duration_mins * 60.0

        node_results = []
        submerged_count = 0
        total_inflow_vol_m3 = 0.0
        total_drained_vol_m3 = 0.0
        total_ponding_vol_m3 = 0.0

        for nid, node in self.nodes.items():
            # Inflow volume: Rational Method runoff Q = (C * I * A) / 3.6e6 m3/s
            inflow_q = (node["runoff_c"] * rain_intensity_mm_hr * node["catchment_area_sqm"]) / 3600000.0
            inflow_vol = inflow_q * storm_duration_sec
            total_inflow_vol_m3 += inflow_vol

            # 2. Dynamic siltation & trash blockage factor
            blockage_calc = self.blockage_engine.calculate(
                flow_depth_y=node["pipe_diameter_m"],
                silt_depth_m=0.25 if "hindmata" in nid or "kings" in nid else 0.12,
                trash_area_sqm=0.15 if "hindmata" in nid else 0.05,
                q_actual=max(0.1, inflow_q)
            )
            n_eff = blockage_calc["effective_manning_n"]

            # 3. 1D Pipe capacity with Preissmann Slot formulation
            pipe = PreissmannSlotPipe(
                diameter_m=node["pipe_diameter_m"],
                slope=node["pipe_slope"],
                manning_n=n_eff
            )

            # Backwater head from locked tidal outfalls
            backwater_head = tide_gate_result["backwater_penalty_m"] if (node["elevation_m"] < 4.5 or "outfall" in nid) else 0.0
            pipe_hydraulics = pipe.compute_discharge(
                stage_y=node["pipe_diameter_m"] * 1.15 if inflow_q > 1.2 else node["pipe_diameter_m"] * 0.8,
                manning_override=n_eff,
                backwater_head_m=backwater_head
            )
            base_drain_q = pipe_hydraulics["discharge_cumecs"]

            # Municipal pump augmentation at key low-lying stations (Britannia, Hindmata tanks)
            effective_drain_q = base_drain_q * pump_factor if ("outfall" in nid or "hindmata" in nid) else base_drain_q
            if tide_gate_result["gate_state"] == "LOCKED_SHUT" and "outfall" in nid:
                # Flap gate shut: gravity outflow halts; drainage relies entirely on BMC pumps
                effective_drain_q = (base_drain_q * 0.15) + (base_drain_q * 0.85 * (pump_power_pct / 100.0))

            surcharge_q = max(0.0, inflow_q - effective_drain_q)
            excess_vol = surcharge_q * storm_duration_sec
            drained_vol = min(inflow_vol, effective_drain_q * storm_duration_sec)
            total_drained_vol_m3 += drained_vol
            total_ponding_vol_m3 += excess_vol

            # 4. Overland ponding depth and underpass depression pooling
            depth_cm = (excess_vol / node["storage_area_sqm"]) * 100.0
            if node.get("is_underpass", False) and surcharge_q > 0.05:
                depth_cm *= 1.35

            # 5. 1D-2D Manhole exchange coupling
            surf_depth_m = depth_cm / 100.0
            h_subterranean = node["elevation_m"] - node["pipe_diameter_m"] + (1.2 * node["pipe_diameter_m"] if pipe_hydraulics["is_pressurized"] else 0.5 * node["pipe_diameter_m"])
            exchange_info = self.exchange_engine.compute_exchange(
                h_2d=surf_depth_m,
                h_1d=h_subterranean,
                z_ground=node["elevation_m"]
            )

            # Hazard category determination
            if depth_cm < 15.0:
                cond_status, status_hex, is_flooded = "PASSABLE", "#22c55e", False
            elif depth_cm < 45.0:
                cond_status, status_hex, is_flooded = "WATERLOGGED", "#f59e0b", True
            else:
                cond_status, status_hex, is_flooded = "IMPASSABLE", "#ef4444", True

            if is_flooded:
                submerged_count += 1

            node_results.append({
                "id": nid,
                "name": node["name"],
                "lat": node["lat"],
                "lon": node["lon"],
                "elevation_m": node["elevation_m"],
                "runoff_m3s": round(inflow_q, 2),
                "pipe_capacity_m3s": round(effective_drain_q, 2),
                "excess_m3s": round(surcharge_q, 2),
                "depth_cm": round(depth_cm, 1),
                "status": cond_status,
                "color": status_hex,
                "is_submerged": is_flooded,
                "is_underpass": node.get("is_underpass", False),
                "notes": node.get("notes", ""),
                "hydrodynamics": {
                    "is_pressurized_slot": pipe_hydraulics["is_pressurized"],
                    "effective_manning_n": n_eff,
                    "blockage_factor_beta": blockage_calc["blockage_factor_beta"],
                    "exchange_regime": exchange_info["regime"],
                    "exchange_q_cumecs": exchange_info["exchange_q_cumecs"]
                }
            })

        # Hospital accessibility checks
        facility_status = []
        for fac in self.services:
            matched = next((n for n in node_results if n["id"] == fac["near_node"]), None)
            inundation_cm = matched["depth_cm"] if matched else 0.0
            service_entry = dict(fac)
            service_entry["water_depth_cm"] = inundation_cm

            if inundation_cm >= 45.0:
                service_entry["alert_level"] = "CRITICAL"
                service_entry["message"] = f"Gate access submerged under {inundation_cm:.0f}cm water. Divert via elevated Tilak Flyover."
            elif inundation_cm >= 15.0:
                service_entry["alert_level"] = "WARNING"
                service_entry["message"] = f"Water ponding at {inundation_cm:.0f}cm outside gate. Accessible by high-clearance vehicles only."
            else:
                service_entry["alert_level"] = "NORMAL"
                service_entry["message"] = "Approach roads dry and clear for patient transit."
            facility_status.append(service_entry)

        # 6. Global mass conservation audit (NHP Standard: Relative Mass Error <= 1.0%)
        mass_audit = HydrographSignalAnalyzer.mass_balance_rme(
            inflow_m3=total_inflow_vol_m3,
            outflow_m3=total_drained_vol_m3,
            storage_change_m3=total_ponding_vol_m3
        )

        # Mithi River stage correlation with Arabian Sea backwater
        mithi_stage_m = 2.40 + (rain_intensity_mm_hr / 45.0) + (0.40 if is_high_tide else 0.0)
        river_status = "DANGER" if mithi_stage_m >= 4.8 else ("WARNING" if mithi_stage_m >= 3.9 else "NORMAL")

        return {
            "params": {
                "rain_mm_hr": rain_intensity_mm_hr,
                "tide_m": tide_level_m,
                "pump_pct": pump_power_pct
            },
            "summary": {
                "total_nodes": len(node_results),
                "flooded_nodes": submerged_count,
                "total_surcharge_m3": round(total_ponding_vol_m3, 0),
                "river_stage_m": round(mithi_stage_m, 2),
                "river_status": river_status,
                "estimated_affected_people": int(submerged_count * 12500),
                "mass_balance_rme_pct": mass_audit["rme_percent"],
                "mass_balance_conserved": mass_audit["is_conserved"]
            },
            "nodes": node_results,
            "facilities": facility_status,
            "phase2_diagnostics": {
                "outfall_gate": tide_gate_result,
                "mass_conservation_audit": mass_audit
            }
        }
