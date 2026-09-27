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

@router.post("/inlet-exchange")
def evaluate_inlet_exchange(exchange_params: ExchangeInput):
    return coupling_model.compute_exchange(
        h_2d=exchange_params.h_2d,
        h_1d=exchange_params.h_1d,
        z_ground=exchange_params.z_ground
    )

@router.post("/lateral-overtopping")
def evaluate_lateral_overtopping(spill_params: LateralOvertoppingInput):
    return coupling_model.lateral_nallah_overtopping(
        h_nallah=spill_params.h_nallah,
        z_bank=spill_params.z_bank,
        h_2d=spill_params.h_2d,
        z_ground=spill_params.z_ground,
        bank_len_m=spill_params.bank_len_m
    )

@router.post("/dynamic-roughness")
def evaluate_dynamic_roughness(roughness_params: DynamicRoughnessInput):
    return roughness_model.calculate(
        flow_depth_y=roughness_params.flow_depth_y,
        silt_depth_m=roughness_params.silt_depth_m,
        trash_area_sqm=roughness_params.trash_area_sqm,
        q_actual=roughness_params.q_actual
    )

@router.post("/tidal-boundary")
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

@router.post("/mass-conservation-audit")
def audit_mass_conservation(audit_params: MassAuditInput):
    return HydrographSignalAnalyzer.mass_balance_rme(
        inflow_m3=audit_params.inflow_m3,
        outflow_m3=audit_params.outflow_m3,
        storage_change_m3=audit_params.storage_change_m3
    )

@router.post("/rate-of-rise")
def evaluate_rate_of_rise(rise_params: RateOfRiseInput):
    return HydrographSignalAnalyzer.rate_of_rise(rise_params.stage_series)

@router.post("/recession-constant")
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
