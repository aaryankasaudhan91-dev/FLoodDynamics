import math
import time
from typing import Dict, Any, Tuple, List

# Phase 2: Coupled 1D-2D Hydrodynamic Modeling Engine
# Localized for Mumbai SWD (Storm Water Drainage) networks:
# Dadar-Hindmata low-lying bowl, Mithi River outfall, and Mahim Bay tidal interface.

class PreissmannSlotPipe:
    """
    1D stormwater pipe hydraulic model with Preissmann Slot formulation.
    Transitions smoothly from open-channel free-surface flow to pressurized
    conduit flow during intense monsoon surcharging without numerical instability.
    """
    def __init__(self, diameter_m: float = 1.0, slope: float = 0.0015, manning_n: float = 0.015):
        self.d = float(diameter_m)
        self.s0 = max(0.0001, float(slope))
        self.n_clean = float(manning_n)
        self.a_full = math.pi * ((self.d / 2.0) ** 2)
        # Numerical wave speed c ~ 150 m/s in urban sewer -> slot width Ts ~ g * A0 / c^2
        self.c_wave = 150.0
        self.slot_width = max(0.008, (9.80665 * self.a_full) / (self.c_wave ** 2))

    def compute_geometry(self, stage_y: float) -> Tuple[float, float, float]:
        # Evaluates wetted area (A), wetted perimeter (P), and hydraulic radius (Rh)
        y = max(0.001, float(stage_y))
        r = self.d / 2.0

        if y < self.d:
            # Partially full circular pipe: theta is wetted subtended angle
            depth_ratio = min(0.999, y / self.d)
            theta = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * depth_ratio)))
            area = (r ** 2) * (theta - math.sin(theta)) / 2.0
            perimeter = r * theta
            hyd_radius = area / max(0.001, perimeter)
        else:
            # Surcharged pipe: physical pipe is full + vertical Preissmann slot
            slot_h = y - self.d
            area = self.a_full + (self.slot_width * slot_h)
            perimeter = (math.pi * self.d) + (2.0 * slot_h)
            hyd_radius = self.a_full / (math.pi * self.d)

        return area, perimeter, hyd_radius

    def compute_discharge(self, stage_y: float, manning_override: float = None, backwater_head_m: float = 0.0) -> Dict[str, Any]:
        area, perim, rh = self.compute_geometry(stage_y)
        n = manning_override if manning_override is not None else self.n_clean

        # Friction slope with backwater attenuation
        eff_slope = max(0.00005, self.s0 - (backwater_head_m / 250.0))
        # Manning's equation: Q = (1/n) * A * Rh^(2/3) * S^(1/2)
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
    """
    Bidirectional hydrodynamic exchange between 1D subterranean conduits
    and 2D overland street grids via catchpits, storm gullies, and manholes.
    """
    def __init__(self, inlet_perimeter_m: float = 2.4, inlet_area_sqm: float = 0.36):
        self.p_m = float(inlet_perimeter_m)
        self.a_m = float(inlet_area_sqm)
        self.g = 9.80665

    def compute_exchange(self, h_2d: float, h_1d: float, z_ground: float) -> Dict[str, Any]:
        # h_2d: water depth on street surface (m)
        # h_1d: hydraulic head inside subsurface drain (m MSL)
        # z_ground: ground elevation (m MSL)
        surf_head = z_ground + max(0.0, float(h_2d))
        delta_head = surf_head - float(h_1d)

        if h_1d > surf_head:
            # Case 1: Manhole boiling / upward surcharge onto street
            # Surcharge regime: water erupts out of manhole covers (common at Hindmata)
            head_diff = h_1d - surf_head
            c_o = 0.58 # orifice discharge coefficient for boiling flow
            q_surch = c_o * self.a_m * math.sqrt(2.0 * self.g * head_diff)
            return {
                "regime": "UPWARD_SURCHARGE",
                "direction": "1D_TO_2D",
                "exchange_q_cumecs": round(q_surch, 3),
                "head_difference_m": round(head_diff, 3),
                "description": "Subterranean hydraulic grade line exceeds street level; water geysering onto road"
            }

        elif h_2d > 0.005:
            # Case 2: Surface runoff draining into underground storm network
            inlet_dia = math.sqrt(4.0 * self.a_m / math.pi)
            if h_2d < 1.5 * inlet_dia:
                # Free-surface weir drop into gully pit
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
                # Deeply submerged orifice capture
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
        # Broad-crested weir overtopping with Villemonte submergence factor
        water_el_nallah = float(h_nallah)
        if water_el_nallah <= float(z_bank):
            return {"spill_q_cumecs": 0.0, "submerged": False, "status": "WITHIN_BANKS"}

        head_above_crest = water_el_nallah - z_bank
        c_dl = 0.38
        q_free = (2.0 / 3.0) * c_dl * bank_len_m * math.sqrt(2.0 * self.g) * (head_above_crest ** 1.5)

        # Check downstream tailwater submergence on adjacent floodplain
        surf_tailwater = z_ground + max(0.0, h_2d)
        if surf_tailwater > z_bank and surf_tailwater < water_el_nallah:
            tw_head = surf_tailwater - z_bank
            # Villemonte submergence scaling
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
    """
    Models Indian urban drainage degradations: silt deposition and solid waste
    (MSW/plastic) trash loading that throttle channel conveyance during monsoons.
    """
    def __init__(self, base_width_m: float = 3.0, clean_manning_n: float = 0.018):
        self.b = float(base_width_m)
        self.n_clean = float(clean_manning_n)
        self.alpha_s = 0.032  # silt stratification coefficient
        self.alpha_w = 0.065  # solid waste drag scalar

    def calculate(self, flow_depth_y: float, silt_depth_m: float = 0.30, trash_area_sqm: float = 0.40, q_actual: float = 5.0) -> Dict[str, Any]:
        y = max(0.10, float(flow_depth_y))
        silt = max(0.0, min(y * 0.85, float(silt_depth_m)))
        a_trash = max(0.0, float(trash_area_sqm))

        design_area = self.b * y
        effective_area = max(0.05, (self.b * (y - silt)) - a_trash)

        # Blockage factor beta: 0 = completely clean, 1 = 100% blocked
        beta = max(0.0, min(0.95, 1.0 - (effective_area / design_area)))

        # Dynamic Manning n adjustment
        silt_ratio = silt / y
        n_eff = (self.n_clean + (self.alpha_s * silt_ratio) + (self.alpha_w * beta))

        # Dry-weather sewage viscous drag penalty
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
    """
    Coastal boundary mechanics for Arabian Sea outfalls (Mahim Bay, Cleaveland Bunder, Love Grove).
    Computes total water level (astronomical tide + storm surge) and flap-gate locking.
    """
    def __init__(self, datum_msl_offset: float = 0.0):
        self.z0 = float(datum_msl_offset)
        # Mumbai tidal harmonic constituents (amplitudes in meters, speeds in deg/hr)
        self.constituents = {
            "M2": {"amp": 1.45, "speed": 28.9841, "phase": 72.0},  # Lunar semi-diurnal
            "S2": {"amp": 0.58, "speed": 30.0000, "phase": 115.0}, # Solar semi-diurnal
            "K1": {"amp": 0.42, "speed": 15.0411, "phase": 195.0}, # Lunisolar diurnal
            "O1": {"amp": 0.22, "speed": 13.9430, "phase": 160.0}  # Lunar diurnal
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
                # Flap gates slam shut under seaward hydrostatic head pressure
                # Small gap leakage (~5% unclosed margin due to trapped debris)
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
                # Un-gated outfall: seawater forces backward into city drainage canal
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
            # Gravity discharge: internal water head pushes open the flap gate
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
    """
    In-situ sensor hydrograph signal processor:
    - Rate of rise (dh/dt) for flash flood detection
    - Recession constant (tau) for drainage clearance speed
    - Mass balance continuity conservation audit (Relative Mass Error <= 1%)
    """
    @staticmethod
    def rate_of_rise(stage_series: List[Dict[str, float]]) -> Dict[str, Any]:
        if not stage_series or len(stage_series) < 2:
            return {"dh_dt_m_per_hr": 0.0, "status": "INSUFFICIENT_DATA"}

        last = stage_series[-1]
        prev = stage_series[-2]
        dt_hr = max(0.001, (last["time"] - prev["time"]) / 3600.0)
        dh = last["stage_m"] - prev["stage_m"]
        rate = round(dh / dt_hr, 3)

        # > 0.05 m/min (~3.0 m/hr) flags approaching flash wave
        is_flash = rate >= 3.0
        return {
            "dh_dt_m_per_hr": rate,
            "dh_dt_m_per_min": round(rate / 60.0, 4),
            "is_flash_surge": is_flash,
            "status": "FLASH_SURGE_WARNING" if is_flash else "STABLE"
        }

    @staticmethod
    def calculate_recession_tau(peak_stage: float, current_stage: float, elapsed_hours: float) -> float:
        # h(t) = h_peak * exp(-t / tau) => tau = -t / ln(h / h_peak)
        if peak_stage <= 0.05 or current_stage <= 0.01 or current_stage >= peak_stage or elapsed_hours <= 0.01:
            return 8.0 # default design clearance hours
        ratio = current_stage / peak_stage
        tau = -elapsed_hours / math.log(ratio)
        return round(max(0.5, min(36.0, tau)), 2)

    @staticmethod
    def mass_balance_rme(inflow_m3: float, outflow_m3: float, storage_change_m3: float) -> Dict[str, Any]:
        vol_in = max(1.0, float(inflow_m3))
        vol_out = float(outflow_m3)
        delta_s = float(storage_change_m3)

        # Global Relative Mass Error (RME) = |Vin - Vout - Delta_S| / Vin * 100
        discrepancy = abs(vol_in - vol_out - delta_s)
        rme_pct = (discrepancy / vol_in) * 100.0
        is_conserved = rme_pct <= 1.0  # NHP standard: RME <= 1.0%

        return {
            "total_inflow_m3": round(vol_in, 1),
            "total_outflow_m3": round(vol_out, 1),
            "storage_change_m3": round(delta_s, 1),
            "mass_discrepancy_m3": round(discrepancy, 1),
            "rme_percent": round(rme_pct, 3),
            "is_conserved": is_conserved,
            "audit_verdict": "PASS (RME <= 1.0%)" if is_conserved else "RECHECK_CONTINUITY"
        }
