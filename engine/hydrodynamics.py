import math
import time
from typing import Dict, Any, Tuple, List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

from .spatial_data import NODES, HOSPITALS_AND_SERVICES

# ---------------------------------------------------------------------------
# Physical Hydraulic Equations
# ---------------------------------------------------------------------------

class PreissmannSlotPipe:
    def __init__(self, diameter_m: float = 1.0, slope: float = 0.0015, manning_n: float = 0.015):
        self.d = float(diameter_m)
        self.s0 = max(0.0001, float(slope))
        self.n_clean = float(manning_n)
        self.a_full = math.pi * ((self.d / 2.0) ** 2)
        self.c_wave = 150.0
        self.slot_width = max(0.008, (9.80665 * self.a_full) / (self.c_wave ** 2))

    def compute_geometry(self, stage_y: float) -> Tuple[float, float, float]:
        y = max(0.001, float(stage_y))
        r = self.d / 2.0

        if y < self.d:
            depth_ratio = min(0.999, y / self.d)
            theta = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * depth_ratio)))
            area = (r ** 2) * (theta - math.sin(theta)) / 2.0
            perimeter = r * theta
            hyd_radius = area / max(0.001, perimeter)
        else:
            slot_h = y - self.d
            area = self.a_full + (self.slot_width * slot_h)
            perimeter = (math.pi * self.d) + (2.0 * slot_h)
            hyd_radius = self.a_full / (math.pi * self.d)

        return area, perimeter, hyd_radius

    def compute_discharge(self, stage_y: float, manning_override: float = None, backwater_head_m: float = 0.0) -> Dict[str, Any]:
        area, perim, rh = self.compute_geometry(stage_y)
        n = manning_override if manning_override is not None else self.n_clean
        eff_slope = max(0.00005, self.s0 - (backwater_head_m / 250.0))
        vel = (1.0 / n) * (rh ** (2.0 / 3.0)) * math.sqrt(eff_slope)
        q = area * vel
        is_pressurized = stage_y > self.d

        return {
            "stage_y_m": round(stage_y, 3),
            "diameter_m": self.d,
            "is_pressurized": is_pressurized,
            "wetted_area_sqm": round(area, 4),
            "hydraulic_radius_m": round(rh, 4),
            "flow_velocity_mps": round(vel, 2),
            "discharge_cumecs": round(q, 3),
            "slot_width_m": round(self.slot_width, 4)
        }


class Coupled1D2DExchange:
    def __init__(self, inlet_perimeter_m: float = 2.4, inlet_area_sqm: float = 0.36):
        self.p_m = float(inlet_perimeter_m)
        self.a_m = float(inlet_area_sqm)
        self.g = 9.80665

    def compute_exchange(self, h_2d: float, h_1d: float, z_ground: float) -> Dict[str, Any]:
        surf_head = z_ground + max(0.0, float(h_2d))
        delta_head = surf_head - float(h_1d)

        if h_1d > surf_head:
            head_diff = h_1d - surf_head
            c_o = 0.58
            q_surch = c_o * self.a_m * math.sqrt(2.0 * self.g * head_diff)
            return {
                "regime": "UPWARD_SURCHARGE",
                "direction": "1D_TO_2D",
                "exchange_q_cumecs": round(q_surch, 3),
                "head_difference_m": round(head_diff, 3),
                "description": "Subterranean hydraulic grade line exceeds street level; water geysering onto road"
            }

        elif h_2d > 0.005:
            inlet_dia = math.sqrt(4.0 * self.a_m / math.pi)
            if h_2d < 1.5 * inlet_dia:
                c_w = 0.48
                q_weir = c_w * self.p_m * (h_2d ** 1.5) * math.sqrt(2.0 * self.g)
                return {
                    "regime": "WEIR_INLET",
                    "direction": "2D_TO_1D",
                    "exchange_q_cumecs": round(q_weir, 3),
                    "head_difference_m": round(delta_head, 3),
                    "description": "Free surface water plunging into drop inlet via weir flow"
                }
            else:
                c_d = 0.60
                driving_head = max(0.01, surf_head - h_1d)
                q_orif = c_d * self.a_m * math.sqrt(2.0 * self.g * driving_head)
                return {
                    "regime": "ORIFICE_INLET",
                    "direction": "2D_TO_1D",
                    "exchange_q_cumecs": round(q_orif, 3),
                    "head_difference_m": round(driving_head, 3),
                    "description": "Submerged street inlet operating under pressurized orifice intake"
                }

        return {
            "regime": "DRY_EQUILIBRIUM",
            "direction": "NONE",
            "exchange_q_cumecs": 0.0,
            "head_difference_m": round(delta_head, 3),
            "description": "No significant surface ponding or subterranean hydraulic gradient"
        }

    def lateral_nallah_overtopping(self, h_nallah: float, z_bank: float, h_2d: float, z_ground: float, bank_len_m: float = 10.0) -> Dict[str, Any]:
        water_el_nallah = float(h_nallah)
        if water_el_nallah <= float(z_bank):
            return {"spill_q_cumecs": 0.0, "submerged": False, "status": "WITHIN_BANKS"}

        head_above_crest = water_el_nallah - z_bank
        c_dl = 0.38
        q_free = (2.0 / 3.0) * c_dl * bank_len_m * math.sqrt(2.0 * self.g) * (head_above_crest ** 1.5)

        surf_tailwater = z_ground + max(0.0, h_2d)
        if surf_tailwater > z_bank and surf_tailwater < water_el_nallah:
            tw_head = surf_tailwater - z_bank
            sub_ratio = min(0.999, tw_head / head_above_crest)
            k_sub = max(0.10, (1.0 - (sub_ratio ** 1.5)) ** 0.385)
            q_actual = q_free * k_sub
            return {
                "spill_q_cumecs": round(q_actual, 3),
                "submerged": True,
                "submergence_reduction_factor": round(k_sub, 3),
                "status": "SUBMERGED_OVERTOPPING"
            }

        return {"spill_q_cumecs": round(q_free, 3), "submerged": False, "status": "FREE_OVERTOPPING"}


class DynamicRoughnessBlockage:
    def __init__(self, base_width_m: float = 3.0, clean_manning_n: float = 0.018):
        self.b = float(base_width_m)
        self.n_clean = float(clean_manning_n)
        self.alpha_s = 0.032
        self.alpha_w = 0.065

    def calculate(self, flow_depth_y: float, silt_depth_m: float = 0.30, trash_area_sqm: float = 0.40, q_actual: float = 5.0) -> Dict[str, Any]:
        y = max(0.10, float(flow_depth_y))
        silt = max(0.0, min(y * 0.85, float(silt_depth_m)))
        a_trash = max(0.0, float(trash_area_sqm))

        design_area = self.b * y
        effective_area = max(0.05, (self.b * (y - silt)) - a_trash)
        beta = max(0.0, min(0.95, 1.0 - (effective_area / design_area)))

        silt_ratio = silt / y
        n_eff = (self.n_clean + (self.alpha_s * silt_ratio) + (self.alpha_w * beta))

        q_dry = 0.40
        if q_actual > 0.01:
            q_ratio = min(2.0, q_dry / q_actual)
            n_eff *= (1.0 + 0.15 * q_ratio)

        capacity_retention_pct = round((1.0 - beta) * 100.0, 1)

        return {
            "flow_depth_m": round(y, 2),
            "silt_depth_m": round(silt, 2),
            "trash_area_sqm": round(a_trash, 2),
            "blockage_factor_beta": round(beta, 3),
            "capacity_retention_pct": capacity_retention_pct,
            "design_manning_n": self.n_clean,
            "effective_manning_n": round(n_eff, 4),
            "conveyance_loss_pct": round(beta * 100.0, 1)
        }


class EstuarineTidalBoundary:
    def __init__(self, datum_msl_offset: float = 0.0):
        self.z0 = float(datum_msl_offset)
        self.constituents = {
            "M2": {"amp": 1.45, "speed": 28.9841, "phase": 72.0},
            "S2": {"amp": 0.58, "speed": 30.0000, "phase": 115.0},
            "K1": {"amp": 0.42, "speed": 15.0411, "phase": 195.0},
            "O1": {"amp": 0.22, "speed": 13.9430, "phase": 160.0}
        }

    def compute_twl(self, hours_from_epoch: float = 0.0, surge_anomaly_m: float = 0.0) -> float:
        t = float(hours_from_epoch)
        tide_h = self.z0
        for name, data in self.constituents.items():
            rad = math.radians((data["speed"] * t) - data["phase"])
            tide_h += data["amp"] * math.cos(rad)

        twl = tide_h + float(surge_anomaly_m)
        return round(twl, 3)

    def evaluate_outfall_gate(self, internal_nallah_head: float, twl_ocean: float, gate_area_sqm: float = 4.0, has_flap_gate: bool = True) -> Dict[str, Any]:
        h_in = float(internal_nallah_head)
        h_sea = float(twl_ocean)
        cd = 0.62

        if h_sea > h_in:
            if has_flap_gate:
                gap_area = gate_area_sqm * 0.05
                head_diff = h_sea - h_in
                leakage_q = cd * gap_area * math.sqrt(2.0 * 9.80665 * head_diff)
                return {
                    "gate_state": "LOCKED_SHUT",
                    "discharge_cumecs": 0.0,
                    "sea_leakage_cumecs": round(leakage_q, 3),
                    "backwater_penalty_m": round(head_diff, 2),
                    "message": "Flap gate sealed against high tide. Outflow blocked; upstream drains surcharging"
                }
            else:
                head_diff = h_sea - h_in
                backflow_q = cd * gate_area_sqm * math.sqrt(2.0 * 9.80665 * head_diff)
                return {
                    "gate_state": "TIDAL_BACKFLOW",
                    "discharge_cumecs": round(-backflow_q, 3),
                    "sea_leakage_cumecs": round(backflow_q, 3),
                    "backwater_penalty_m": round(head_diff, 2),
                    "message": "Seawater pushing inland into urban network via reverse pressure gradient"
                }
        else:
            eff_head = h_in - h_sea
            outflow_q = cd * gate_area_sqm * math.sqrt(2.0 * 9.80665 * eff_head)
            return {
                "gate_state": "DISCHARGING",
                "discharge_cumecs": round(outflow_q, 3),
                "sea_leakage_cumecs": 0.0,
                "backwater_penalty_m": 0.0,
                "message": "Gravity drainage active; outfall operating with positive seaward gradient"
            }


class HydrographSignalAnalyzer:
    @staticmethod
    def rate_of_rise(stage_series: List[Dict[str, float]]) -> Dict[str, Any]:
        if not stage_series or len(stage_series) < 2:
            return {"dh_dt_m_per_hr": 0.0, "status": "INSUFFICIENT_DATA"}

        last = stage_series[-1]
        prev = stage_series[-2]
        dt_hr = max(0.001, (last["time"] - prev["time"]) / 3600.0)
        dh = last["stage_m"] - prev["stage_m"]
        rate = round(dh / dt_hr, 3)

        is_flash = rate >= 3.0
        return {
            "dh_dt_m_per_hr": rate,
            "dh_dt_m_per_min": round(rate / 60.0, 4),
            "is_flash_surge": is_flash,
            "status": "FLASH_SURGE_WARNING" if is_flash else "STABLE"
        }

    @staticmethod
    def calculate_recession_tau(peak_stage: float, current_stage: float, elapsed_hours: float) -> float:
        if peak_stage <= 0.05 or current_stage <= 0.01 or current_stage >= peak_stage or elapsed_hours <= 0.01:
            return 8.0
        ratio = current_stage / peak_stage
        tau = -elapsed_hours / math.log(ratio)
        return round(max(0.5, min(36.0, tau)), 2)

    @staticmethod
    def mass_balance_rme(inflow_m3: float, outflow_m3: float, storage_change_m3: float) -> Dict[str, Any]:
        vol_in = max(1.0, float(inflow_m3))
        vol_out = float(outflow_m3)
        delta_s = float(storage_change_m3)

        discrepancy = abs(vol_in - vol_out - delta_s)
        rme_pct = (discrepancy / vol_in) * 100.0
        is_conserved = rme_pct <= 1.0

        return {
            "total_inflow_m3": round(vol_in, 1),
            "total_outflow_m3": round(vol_out, 1),
            "storage_change_m3": round(delta_s, 1),
            "mass_discrepancy_m3": round(discrepancy, 1),
            "rme_percent": round(rme_pct, 3),
            "is_conserved": is_conserved,
            "audit_verdict": "PASS (RME <= 1.0%)" if is_conserved else "RECHECK_CONTINUITY"
        }


# ---------------------------------------------------------------------------
# Simulation Orchestrator
# ---------------------------------------------------------------------------

class HydraulicModel:
    def __init__(self):
        self.nodes = {n["id"]: dict(n) for n in NODES}
        self.services = [dict(s) for s in HOSPITALS_AND_SERVICES]
        self.tidal_engine = EstuarineTidalBoundary()
        self.exchange_engine = Coupled1D2DExchange()
        self.blockage_engine = DynamicRoughnessBlockage()

    def simulate(self, rain_intensity_mm_hr: float = 15.0, tide_level_m: float = 2.0, pump_power_pct: float = 100.0, duration_mins: float = 25.0) -> Dict[str, Any]:
        twl_ocean = float(tide_level_m)
        is_high_tide = twl_ocean > 3.5
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
            inflow_q = (node["runoff_c"] * rain_intensity_mm_hr * node["catchment_area_sqm"]) / 3600000.0
            inflow_vol = inflow_q * storm_duration_sec
            total_inflow_vol_m3 += inflow_vol

            blockage_calc = self.blockage_engine.calculate(
                flow_depth_y=node["pipe_diameter_m"],
                silt_depth_m=0.25 if "hindmata" in nid or "kings" in nid else 0.12,
                trash_area_sqm=0.15 if "hindmata" in nid else 0.05,
                q_actual=max(0.1, inflow_q)
            )
            n_eff = blockage_calc["effective_manning_n"]

            pipe = PreissmannSlotPipe(
                diameter_m=node["pipe_diameter_m"],
                slope=node["pipe_slope"],
                manning_n=n_eff
            )

            backwater_head = tide_gate_result["backwater_penalty_m"] if (node["elevation_m"] < 4.5 or "outfall" in nid) else 0.0
            pipe_hydraulics = pipe.compute_discharge(
                stage_y=node["pipe_diameter_m"] * 1.15 if inflow_q > 1.2 else node["pipe_diameter_m"] * 0.8,
                manning_override=n_eff,
                backwater_head_m=backwater_head
            )
            base_drain_q = pipe_hydraulics["discharge_cumecs"]

            effective_drain_q = base_drain_q * pump_factor if ("outfall" in nid or "hindmata" in nid) else base_drain_q
            if tide_gate_result["gate_state"] == "LOCKED_SHUT" and "outfall" in nid:
                effective_drain_q = (base_drain_q * 0.15) + (base_drain_q * 0.85 * (pump_power_pct / 100.0))

            surcharge_q = max(0.0, inflow_q - effective_drain_q)
            excess_vol = surcharge_q * storm_duration_sec
            drained_vol = min(inflow_vol, effective_drain_q * storm_duration_sec)
            total_drained_vol_m3 += drained_vol
            total_ponding_vol_m3 += excess_vol

            depth_cm = (excess_vol / node["storage_area_sqm"]) * 100.0
            if node.get("is_underpass", False) and surcharge_q > 0.05:
                depth_cm *= 1.35

            surf_depth_m = depth_cm / 100.0
            h_subterranean = node["elevation_m"] - node["pipe_diameter_m"] + (1.2 * node["pipe_diameter_m"] if pipe_hydraulics["is_pressurized"] else 0.5 * node["pipe_diameter_m"])
            exchange_info = self.exchange_engine.compute_exchange(
                h_2d=surf_depth_m,
                h_1d=h_subterranean,
                z_ground=node["elevation_m"]
            )

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

        mass_audit = HydrographSignalAnalyzer.mass_balance_rme(
            inflow_m3=total_inflow_vol_m3,
            outflow_m3=total_drained_vol_m3,
            storage_change_m3=total_ponding_vol_m3
        )

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


# ---------------------------------------------------------------------------
# Phase 2 FastAPI Router
# ---------------------------------------------------------------------------

phase2_router = APIRouter(prefix="/api/v2/hydro", tags=["Phase 2 Hydrodynamics"])

tidal_model = EstuarineTidalBoundary()
coupling_model = Coupled1D2DExchange()
roughness_model = DynamicRoughnessBlockage()

class PreissmannInput(BaseModel):
    diameter_m: float = 1.0
    stage_y: float = 1.2
    slope: float = 0.0015
    manning_n: float = 0.015
    backwater_head_m: float = 0.0

class ExchangeInput(BaseModel):
    h_2d: float = 0.20
    h_1d: float = 4.90
    z_ground: float = 4.50

class LateralOvertoppingInput(BaseModel):
    h_nallah: float = 5.20
    z_bank: float = 4.80
    h_2d: float = 0.10
    z_ground: float = 4.40
    bank_len_m: float = 15.0

class DynamicRoughnessInput(BaseModel):
    flow_depth_y: float = 1.20
    silt_depth_m: float = 0.25
    trash_area_sqm: float = 0.15
    q_actual: float = 4.5

class TidalBoundaryInput(BaseModel):
    hours_from_epoch: float = 6.0
    surge_anomaly_m: float = 0.25
    internal_nallah_head: float = 3.20
    has_flap_gate: bool = True

class MassAuditInput(BaseModel):
    inflow_m3: float = 15000.0
    outflow_m3: float = 11200.0
    storage_change_m3: float = 3800.0

class RateOfRiseInput(BaseModel):
    stage_series: List[Dict[str, float]]

class RecessionInput(BaseModel):
    peak_stage: float = 4.80
    current_stage: float = 2.40
    elapsed_hours: float = 3.5

@phase2_router.post("/preissmann-conduit")
def evaluate_preissmann_conduit(pipe_params: PreissmannInput):
    pipe = PreissmannSlotPipe(
        diameter_m=pipe_params.diameter_m,
        slope=pipe_params.slope,
        manning_n=pipe_params.manning_n
    )
    return pipe.compute_discharge(
        stage_y=pipe_params.stage_y,
        backwater_head_m=pipe_params.backwater_head_m
    )

@phase2_router.post("/inlet-exchange")
def evaluate_inlet_exchange(exchange_params: ExchangeInput):
    return coupling_model.compute_exchange(
        h_2d=exchange_params.h_2d,
        h_1d=exchange_params.h_1d,
        z_ground=exchange_params.z_ground
    )

@phase2_router.post("/lateral-overtopping")
def evaluate_lateral_overtopping(spill_params: LateralOvertoppingInput):
    return coupling_model.lateral_nallah_overtopping(
        h_nallah=spill_params.h_nallah,
        z_bank=spill_params.z_bank,
        h_2d=spill_params.h_2d,
        z_ground=spill_params.z_ground,
        bank_len_m=spill_params.bank_len_m
    )

@phase2_router.post("/dynamic-roughness")
def evaluate_dynamic_roughness(roughness_params: DynamicRoughnessInput):
    return roughness_model.calculate(
        flow_depth_y=roughness_params.flow_depth_y,
        silt_depth_m=roughness_params.silt_depth_m,
        trash_area_sqm=roughness_params.trash_area_sqm,
        q_actual=roughness_params.q_actual
    )

@phase2_router.post("/tidal-boundary")
def evaluate_tidal_boundary(tidal_params: TidalBoundaryInput):
    twl = tidal_model.compute_twl(
        hours_from_epoch=tidal_params.hours_from_epoch,
        surge_anomaly_m=tidal_params.surge_anomaly_m
    )
    gate_eval = tidal_model.evaluate_outfall_gate(
        internal_nallah_head=tidal_params.internal_nallah_head,
        twl_ocean=twl,
        has_flap_gate=tidal_params.has_flap_gate
    )
    return {
        "ocean_twl_m": twl,
        "hours_from_epoch": tidal_params.hours_from_epoch,
        "surge_anomaly_m": tidal_params.surge_anomaly_m,
        "outfall_gate": gate_eval
    }

@phase2_router.post("/mass-conservation-audit")
def audit_mass_conservation(audit_params: MassAuditInput):
    return HydrographSignalAnalyzer.mass_balance_rme(
        inflow_m3=audit_params.inflow_m3,
        outflow_m3=audit_params.outflow_m3,
        storage_change_m3=audit_params.storage_change_m3
    )

@phase2_router.post("/rate-of-rise")
def evaluate_rate_of_rise(rise_params: RateOfRiseInput):
    return HydrographSignalAnalyzer.rate_of_rise(rise_params.stage_series)

@phase2_router.post("/recession-constant")
def evaluate_recession(recession_params: RecessionInput):
    tau = HydrographSignalAnalyzer.calculate_recession_tau(
        peak_stage=recession_params.peak_stage,
        current_stage=recession_params.current_stage,
        elapsed_hours=recession_params.elapsed_hours
    )
    return {
        "peak_stage_m": recession_params.peak_stage,
        "current_stage_m": recession_params.current_stage,
        "elapsed_hours": recession_params.elapsed_hours,
        "recession_time_constant_tau_hr": tau,
        "drainage_speed": "FAST" if tau <= 4.0 else ("NORMAL" if tau <= 8.0 else "CHRONIC_BLOCKAGE_ALERT")
    }
