from typing import Optional, List, Dict
from fastapi import APIRouter
from pydantic import BaseModel

from .phase2_hydrodynamics import (
    PreissmannSlotPipe,
    Coupled1D2DExchange,
    DynamicRoughnessBlockage,
    EstuarineTidalBoundary,
    HydrographSignalAnalyzer
)

router = APIRouter(prefix="/api/v2/hydro", tags=["Phase 2 Hydrodynamics"])

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

@router.post("/preissmann-conduit")
def evaluate_preissmann_conduit(data: PreissmannInput):
    pipe = PreissmannSlotPipe(
        diameter_m=data.diameter_m,
        slope=data.slope,
        manning_n=data.manning_n
    )
    return pipe.compute_discharge(
        stage_y=data.stage_y,
        backwater_head_m=data.backwater_head_m
    )

@router.post("/inlet-exchange")
def evaluate_inlet_exchange(data: ExchangeInput):
    return coupling_model.compute_exchange(
        h_2d=data.h_2d,
        h_1d=data.h_1d,
        z_ground=data.z_ground
    )

@router.post("/lateral-overtopping")
def evaluate_lateral_overtopping(data: LateralOvertoppingInput):
    return coupling_model.lateral_nallah_overtopping(
        h_nallah=data.h_nallah,
        z_bank=data.z_bank,
        h_2d=data.h_2d,
        z_ground=data.z_ground,
        bank_len_m=data.bank_len_m
    )

@router.post("/dynamic-roughness")
def evaluate_dynamic_roughness(data: DynamicRoughnessInput):
    return roughness_model.calculate(
        flow_depth_y=data.flow_depth_y,
        silt_depth_m=data.silt_depth_m,
        trash_area_sqm=data.trash_area_sqm,
        q_actual=data.q_actual
    )

@router.post("/tidal-boundary")
def evaluate_tidal_boundary(data: TidalBoundaryInput):
    twl = tidal_model.compute_twl(
        hours_from_epoch=data.hours_from_epoch,
        surge_anomaly_m=data.surge_anomaly_m
    )
    gate_eval = tidal_model.evaluate_outfall_gate(
        internal_nallah_head=data.internal_nallah_head,
        twl_ocean=twl,
        has_flap_gate=data.has_flap_gate
    )
    return {
        "ocean_twl_m": twl,
        "hours_from_epoch": data.hours_from_epoch,
        "surge_anomaly_m": data.surge_anomaly_m,
        "outfall_gate": gate_eval
    }

@router.post("/mass-conservation-audit")
def audit_mass_conservation(data: MassAuditInput):
    return HydrographSignalAnalyzer.mass_balance_rme(
        inflow_m3=data.inflow_m3,
        outflow_m3=data.outflow_m3,
        storage_change_m3=data.storage_change_m3
    )

@router.post("/rate-of-rise")
def evaluate_rate_of_rise(data: RateOfRiseInput):
    return HydrographSignalAnalyzer.rate_of_rise(data.stage_series)

@router.post("/recession-constant")
def evaluate_recession(data: RecessionInput):
    tau = HydrographSignalAnalyzer.calculate_recession_tau(
        peak_stage=data.peak_stage,
        current_stage=data.current_stage,
        elapsed_hours=data.elapsed_hours
    )
    return {
        "peak_stage_m": data.peak_stage,
        "current_stage_m": data.current_stage,
        "elapsed_hours": data.elapsed_hours,
        "recession_time_constant_tau_hr": tau,
        "drainage_speed": "FAST" if tau <= 4.0 else ("NORMAL" if tau <= 8.0 else "CHRONIC_BLOCKAGE_ALERT")
    }
