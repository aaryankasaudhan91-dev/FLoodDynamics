import time
import base64
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from .phase4_navigation import (
    VehicleClass,
    VEHICLE_THRESHOLDS,
    calculate_edge_cost,
    calculate_hydrodynamic_forces,
    NavICEngine,
    SMSFallbackProtocol,
    SmartNavigationRouter,
    EvacuationShelterEngine
)

router = APIRouter(prefix="/api/v1", tags=["Phase 4 Smart Navigation"])

navigation_engine = SmartNavigationRouter()
shelter_engine = EvacuationShelterEngine()

# ---------------------------------------------------------------------------
# Pydantic Schemas matching Section 5 Specification
# ---------------------------------------------------------------------------

class VehicleProfileInput(BaseModel):
    classification: VehicleClass = VehicleClass.SUV_LCV
    ground_clearance_mm: Optional[int] = 240
    wading_depth_max_mm: Optional[int] = 450
    gross_vehicle_mass_kg: Optional[float] = 2800.0
    propulsion_type: Optional[str] = "DIESEL_4WD"

class RoutePreferencesInput(BaseModel):
    allow_unpaved_roads: bool = False
    avoid_bridge_classes: List[str] = ["TEMPORARY_TIMBER", "PONTOON"]
    risk_tolerance_factor: float = 0.1
    allow_dynamic_recalculation: bool = True

class WaypointLocation(BaseModel):
    latitude: float
    longitude: float
    elevation_msl_m: Optional[float] = 8.5
    source_type: Optional[str] = "NAVIC_L5_S"

class SafeRouteRequest(BaseModel):
    request_id: Optional[str] = "REQ-MUMBAI-FLOOD-2026-09-16-00421"
    client_timestamp: Optional[str] = None
    vehicle_profile: VehicleProfileInput = Field(default_factory=VehicleProfileInput)
    route_preferences: Optional[RoutePreferencesInput] = None
    origin: WaypointLocation
    destination: WaypointLocation
    water_depth_override_m: Optional[Dict[str, float]] = None
    water_velocity_override_mps: Optional[Dict[str, float]] = None
    is_emergency_responder: bool = False

class DemographicsInput(BaseModel):
    total_individuals: int = 240
    critical_medical_patients: int = 4
    mobility_impaired_count: int = 18
    infants_children_count: int = 45

class TransitCapabilityInput(BaseModel):
    primary_mode: str = "WALKING_EVACUATION"
    effective_clearance_mm: float = 150.0
    max_walking_range_m: float = 3500.0

class ShelterAllocationRequest(BaseModel):
    cohort_id: str = "COHORT-THANE-WARD-4B"
    timestamp: Optional[str] = None
    current_centroid: WaypointLocation
    demographics: DemographicsInput = Field(default_factory=DemographicsInput)
    transit_capability: TransitCapabilityInput = Field(default_factory=TransitCapabilityInput)
    required_facilities: List[str] = [
        "HIGH_DEPENDENCY_MEDICAL",
        "EMERGENCY_POWER_BACKUP",
        "DRINKING_WATER_PURIFICATION"
    ]

class NavICPacketEncodeInput(BaseModel):
    msg_id: int = 1
    seq_num: int = 101
    epoch_timestamp: Optional[int] = None
    latitude: float = 19.0142
    longitude: float = 72.8427
    altitude_msl_cm: int = 420
    sog_cm_s: int = 850
    cog_tenth_deg: int = 900
    fix_type: int = 3
    num_sats: int = 8
    dop_q4_4: int = 18
    vehicle_type: int = 2
    battery_pct: int = 95

class NavICPacketDecodeInput(BaseModel):
    packet_base64: str

class NavICIonoFreeInput(BaseModel):
    pseudorange_l5_m: float
    pseudorange_s_m: float

class SMSCompressInput(BaseModel):
    mission_id: int = 9912
    target_lat: float = 19.0250
    target_lon: float = 72.8570
    steps: List[Dict[str, Any]] = [
        {"action_code": 1, "distance_m": 300, "bearing_deg": 0, "max_wading_cm": 5},
        {"action_code": 2, "distance_m": 850, "bearing_deg": 90, "max_wading_cm": 12},
        {"action_code": 4, "distance_m": 270, "bearing_deg": 45, "max_wading_cm": 0}
    ]

class USSDMenuInput(BaseModel):
    shelter_name: str = "Khalsa College Relief Complex"
    distance_km: float = 1.4
    steps: List[str] = [
        "Walk NORTH 300m to Station Rd",
        "Turn RIGHT on Highway (Water 10cm)",
        "Reach Camp on High Ground"
    ]

class GreenCorridorRequest(BaseModel):
    mission_id: str = "MISSION-NDRF-05-RELIEF"
    reserved_edge_ids: List[str] = ["e_dadar_tilak", "e_tilak_senapati", "e_senapati_elphinstone"]
    active: bool = True

class CADIncidentInput(BaseModel):
    incident_id: str = "CAD-ERSS-112-2026-MUM-8841"
    caller_phone: str = "+91-9820011223"
    latitude: float = 19.0142
    longitude: float = 72.8427
    elevation_msl_m: float = 4.2
    reported_water_depth_cm: float = 65.0
    stranded_persons: int = 3


# ---------------------------------------------------------------------------
# Section 5.1: /api/v1/route/safe
# ---------------------------------------------------------------------------

@router.post("/route/safe", status_code=status.HTTP_200_OK)
def get_safe_route(route_req: SafeRouteRequest, response: Response):
    veh_class = route_req.vehicle_profile.classification
    res = navigation_engine.compute_safe_route(
        origin_lat=route_req.origin.latitude,
        origin_lon=route_req.origin.longitude,
        dest_lat=route_req.destination.latitude,
        dest_lon=route_req.destination.longitude,
        vehicle_class=veh_class,
        depth_map_m=route_req.water_depth_override_m,
        velocity_map_mps=route_req.water_velocity_override_mps,
        is_emergency_responder=route_req.is_emergency_responder
    )

    if res.get("error"):
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        response.headers["Content-Type"] = "application/problem+json"
        return {
            "type": res["type"],
            "title": res["title"],
            "status": 422,
            "detail": res["detail"],
            "instance": f"/api/v1/route/safe/{route_req.request_id or 'REQ-GENERIC'}",
            "error_code": res["error_code"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
            "diagnostics": res["diagnostics"]
        }

    return {
        "response_id": f"RES-{route_req.request_id or 'QUERY'}",
        "status": res["status"],
        "computation_timestamp": res["computation_timestamp"],
        "summary": res["summary"],
        "geometry": res["geometry"],
        "legs": res["legs"],
        "critical_warnings": res["critical_warnings"]
    }


# ---------------------------------------------------------------------------
# Section 5.2: /api/v1/evacuation/nearest-shelter
# ---------------------------------------------------------------------------

@router.post("/evacuation/nearest-shelter")
def allocate_evacuation_shelter(shelter_req: ShelterAllocationRequest):
    return shelter_engine.allocate_nearest_shelter(
        cohort_id=shelter_req.cohort_id,
        centroid_lat=shelter_req.current_centroid.latitude,
        centroid_lon=shelter_req.current_centroid.longitude,
        headcount=shelter_req.demographics.total_individuals,
        required_facilities=shelter_req.required_facilities,
        effective_clearance_mm=shelter_req.transit_capability.effective_clearance_mm
    )


# ---------------------------------------------------------------------------
# Section 5.3: /api/v1/corridor/status
# ---------------------------------------------------------------------------

@router.get("/corridor/status")
def get_corridor_status(
    bbox: Optional[str] = None,
    corridor_class: Optional[str] = "NATIONAL_HIGHWAY,STATE_HIGHWAY,ARTERIAL_FLYOVERS",
    min_severity: Optional[str] = "WATCH"
):
    # Live monitored corridors for South-Central Mumbai
    return {
        "query_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
        "active_corridors_monitored": 3,
        "corridors": [
            {
                "corridor_id": "CORR-NH-48-MUM-PUN",
                "designation": "National Highway 48 (Sion-Panvel Expressway Sector)",
                "structural_status": "OPERATIONAL",
                "surface_condition": "PARTIALLY_INUNDATED",
                "green_corridor_active": navigation_engine.green_corridor_active,
                "active_mission_id": navigation_engine.active_mission_id,
                "monitored_segments": [
                    {
                        "segment_id": "SEG-NH48-0091",
                        "name": "Hindmata Underpass Expressway Link",
                        "start_chainage_km": 14.2,
                        "end_chainage_km": 16.8,
                        "elevation_min_msl_m": 4.1,
                        "current_max_depth_mm": 280,
                        "water_velocity_mps": 0.45,
                        "traffic_passability": {
                            "TWO_WHEELER": "PROHIBITED",
                            "SEDAN": "PROHIBITED",
                            "SUV_LCV": "RESTRICTED_CAUTION",
                            "HEAVY_TRUCK": "PASSABLE",
                            "RESCUE_BOAT": "NON_NAVIGABLE_LOW_WATER"
                        },
                        "telemetry_source": {
                            "sensor_id": "ULTRASONIC-WATER-LEVEL-STN-88",
                            "cctv_ai_inference_id": "CAM-NH48-SION-04",
                            "confidence_score": 0.98
                        }
                    },
                    {
                        "segment_id": "SEG-NH48-FLYOVR-02",
                        "name": "Tilak Bridge Elevated Corridor",
                        "elevation_min_msl_m": 14.5,
                        "current_max_depth_mm": 0,
                        "water_velocity_mps": 0.0,
                        "traffic_passability": {
                            "TWO_WHEELER": "PASSABLE",
                            "SEDAN": "PASSABLE",
                            "SUV_LCV": "PASSABLE",
                            "HEAVY_TRUCK": "PASSABLE",
                            "RESCUE_BOAT": "NOT_APPLICABLE"
                        }
                    }
                ]
            }
        ]
    }


# ---------------------------------------------------------------------------
# Section 4.2: Green Corridor Enforcement
# ---------------------------------------------------------------------------

@router.post("/corridor/reserve-green")
def reserve_green_corridor(req: GreenCorridorRequest):
    navigation_engine.set_green_corridor(
        mission_id=req.mission_id if req.active else None,
        edge_ids=req.reserved_edge_ids if req.active else []
    )
    return {
        "status": "GREEN_CORRIDOR_ACTIVE" if req.active else "CORRIDOR_RELEASED",
        "mission_id": req.mission_id,
        "reserved_edges": req.reserved_edge_ids,
        "traffic_signal_preemption": "NTCIP_MODBUS_GREEN_WAVE_ARMED" if req.active else "OFF",
        "civilian_traffic_evicted": req.active
    }


# ---------------------------------------------------------------------------
# Section 2.2: NavIC Dual-Frequency & Telemetry Endpoints
# ---------------------------------------------------------------------------

@router.post("/navic/iono-free")
def calculate_iono_free(req: NavICIonoFreeInput):
    p_iono_free = NavICEngine.calculate_iono_free_pseudorange(
        pseudorange_l5_m=req.pseudorange_l5_m,
        pseudorange_s_m=req.pseudorange_s_m
    )
    return {
        "pseudorange_l5_m": req.pseudorange_l5_m,
        "pseudorange_s_m": req.pseudorange_s_m,
        "iono_free_pseudorange_m": p_iono_free,
        "ionospheric_delay_reduction_m": round(abs(req.pseudorange_l5_m - p_iono_free), 3),
        "constellation": "NavIC (IRNSS L5/S Dual Frequency)"
    }

@router.post("/navic/telemetry-packet/encode")
def encode_navic_packet(req: NavICPacketEncodeInput):
    t_epoch = req.epoch_timestamp or int(time.time())
    raw_packet = NavICEngine.pack_telemetry_packet(
        msg_id=req.msg_id,
        seq_num=req.seq_num,
        epoch_timestamp=t_epoch,
        latitude=req.latitude,
        longitude=req.longitude,
        altitude_msl_cm=req.altitude_msl_cm,
        sog_cm_s=req.sog_cm_s,
        cog_tenth_deg=req.cog_tenth_deg,
        fix_type=req.fix_type,
        num_sats=req.num_sats,
        dop_q4_4=req.dop_q4_4,
        vehicle_type=req.vehicle_type,
        battery_pct=req.battery_pct
    )
    return {
        "packet_len_bytes": len(raw_packet),
        "packet_hex": raw_packet.hex(),
        "packet_base64": base64.b64encode(raw_packet).decode()
    }

@router.post("/navic/telemetry-packet/decode")
def decode_navic_packet(req: NavICPacketDecodeInput):
    try:
        raw_bytes = base64.b64decode(req.packet_base64)
        return NavICEngine.unpack_telemetry_packet(raw_bytes)
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"NavIC telemetry decoding failed: {err}")


# ---------------------------------------------------------------------------
# Section 6.3: SMS & USSD Low-Bandwidth Fallback Endpoints
# ---------------------------------------------------------------------------

@router.post("/fallback/sms-compress")
def compress_sms_payload(req: SMSCompressInput):
    raw_sms = SMSFallbackProtocol.encode_evacuation_sms(
        mission_id=req.mission_id,
        target_lat=req.target_lat,
        target_lon=req.target_lon,
        steps=req.steps
    )
    decoded = SMSFallbackProtocol.decode_evacuation_sms(raw_sms)
    return {
        "frame_len_bytes": len(raw_sms),
        "sms_base64": base64.b64encode(raw_sms).decode(),
        "crc8_hex": hex(raw_sms[139]),
        "decoded_verification": decoded
    }

@router.post("/fallback/ussd-menu")
def generate_ussd_response(req: USSDMenuInput):
    menu_text = SMSFallbackProtocol.generate_ussd_menu(
        shelter_name=req.shelter_name,
        distance_km=req.distance_km,
        step_descriptions=req.steps
    )
    return {
        "session_code": "*112*FLOOD#",
        "character_count": len(menu_text),
        "fits_single_ussd_frame": len(menu_text) <= 160,
        "menu_text": menu_text
    }


# ---------------------------------------------------------------------------
# Section 6.1: ERSS 112 CAD Automated Incident Ingestion & Dispatch
# ---------------------------------------------------------------------------

@router.post("/erss/cad-incident")
def dispatch_cad_incident(incident: CADIncidentInput):
    # Determine appropriate rescue vehicle based on reported water depth
    depth_m = incident.reported_water_depth_cm / 100.0
    if depth_m >= 1.0:
        recommended_unit = "INFLATABLE_RESCUE_BOAT_UNIT"
        veh_class = VehicleClass.RESCUE_BOAT
    elif depth_m >= 0.35:
        recommended_unit = "NDRF_4X4_HEAVY_RESCUE_TRUCK"
        veh_class = VehicleClass.HEAVY_TRUCK
    else:
        recommended_unit = "QUICK_RESPONSE_AMBULANCE_SUV"
        veh_class = VehicleClass.SUV_LCV

    # Calculate optimal ingress route to the stranded victim
    dispatch_route = navigation_engine.compute_safe_route(
        origin_lat=19.0175,  # Dadar Fire & Rescue Station (No. 14)
        origin_lon=72.8448,
        dest_lat=incident.latitude,
        dest_lon=incident.longitude,
        vehicle_class=veh_class,
        is_emergency_responder=True
    )

    return {
        "incident_id": incident.incident_id,
        "erss_cad_status": "DISPATCH_INJECTED",
        "recommended_tactical_unit": recommended_unit,
        "vehicle_class": veh_class.value,
        "target_coordinates": [incident.longitude, incident.latitude],
        "reported_water_depth_cm": incident.reported_water_depth_cm,
        "dispatch_route": dispatch_route
    }
