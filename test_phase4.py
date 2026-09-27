import base64
from fastapi.testclient import TestClient
from main import app
from engine.navigation import (
    VehicleClass,
    VEHICLE_THRESHOLDS,
    calculate_edge_cost,
    calculate_hydrodynamic_forces,
    NavICEngine,
    SMSFallbackProtocol,
    SmartNavigationRouter,
    EvacuationShelterEngine
)

client = TestClient(app)

def test_phase4_all():
    print("Running FloodGuard Phase 4 Smart Navigation Test Suite...\n")

    # 1. Mathematical Edge Cost Formulation
    # Dry baseline: L=500m, speed=36 km/h (10 m/s) -> tau_0 = 50.0s
    cost_dry = calculate_edge_cost(
        length_m=500.0,
        free_speed_kmh=36.0,
        water_depth_m=0.0,
        water_velocity_mps=0.0,
        structural_failure=False,
        vehicle_class=VehicleClass.SEDAN
    )
    assert abs(cost_dry - 50.0) < 0.1, f"Dry cost mismatch: {cost_dry}"
    print(f"[PASS] Baseline traversal cost: L=500m @ 36km/h -> {cost_dry:.1f}s")

    # Non-linear penalty: h=0.15m (h_crit=0.25), v=0.5m/s (v_crit=1.0)
    # depth_ratio = 0.6, velocity_ratio = 0.5
    # penalty = 1.0 + 4.5*(0.6^2) + 3.0*(0.5^1.8) = 1.0 + 4.5*0.36 + 3.0*0.287 = 1.0 + 1.62 + 0.861 = 3.481
    # cost = 50 * 3.481 = ~174.1s
    cost_flooded = calculate_edge_cost(
        length_m=500.0,
        free_speed_kmh=36.0,
        water_depth_m=0.15,
        water_velocity_mps=0.50,
        structural_failure=False,
        vehicle_class=VehicleClass.SEDAN
    )
    assert cost_flooded is not None and cost_flooded > 150.0, f"Expected flooded penalty, got {cost_flooded}"
    print(f"[PASS] Inundation penalty formulation: h=15cm, v=0.5m/s -> cost={cost_flooded:.1f}s (penalty factor {cost_flooded/cost_dry:.2f}x)")

    # Impassable condition: h >= h_crit (0.25m for Sedan)
    cost_blocked = calculate_edge_cost(
        length_m=500.0,
        free_speed_kmh=36.0,
        water_depth_m=0.28,
        water_velocity_mps=0.20,
        structural_failure=False,
        vehicle_class=VehicleClass.SEDAN
    )
    assert cost_blocked is None, "Should block sedan when depth exceeds 25cm"
    print("[PASS] Vehicle critical threshold: h=28cm > h_crit(25cm) -> Edge BLOCKED (None)")

    # Rescue Boat physics: grounded in shallow water, navigable in deep water
    boat_shallow = calculate_edge_cost(
        length_m=500.0,
        free_speed_kmh=25.0,
        water_depth_m=0.15, # < draft 0.30m
        water_velocity_mps=0.50,
        structural_failure=False,
        vehicle_class=VehicleClass.RESCUE_BOAT
    )
    assert boat_shallow is None, "Rescue boat should ground in <30cm water"

    boat_navigable = calculate_edge_cost(
        length_m=500.0,
        free_speed_kmh=25.0,
        water_depth_m=1.20,
        water_velocity_mps=1.00,
        structural_failure=False,
        vehicle_class=VehicleClass.RESCUE_BOAT
    )
    assert boat_navigable is not None, "Rescue boat should navigate deep water"
    print(f"[PASS] Rescue boat draft threshold: shallow (<30cm) -> BLOCKED; deep (1.2m) -> NAVIGABLE ({boat_navigable:.1f}s)")

    # 2. Hydrodynamic Force & Safety Margin Analysis
    hydro_forces = calculate_hydrodynamic_forces(
        vehicle_class=VehicleClass.SUV_LCV,
        water_depth_m=0.30,
        water_velocity_mps=0.80
    )
    assert hydro_forces["buoyancy_force_n"] > 0
    assert hydro_forces["drag_force_n"] > 0
    assert hydro_forces["safety_margin"] > 0
    print(f"[PASS] Hydrodynamic forces: Buoyancy={hydro_forces['buoyancy_force_n']}N, Drag={hydro_forces['drag_force_n']}N, Margin={hydro_forces['safety_margin']}")

    # 3. NavIC Dual-Frequency Iono-Free Correction
    # Synthetic delay: L5=20,000,012.0m, S=20,000,004.0m
    iono_free = NavICEngine.calculate_iono_free_pseudorange(
        pseudorange_l5_m=20000012.0,
        pseudorange_s_m=20000004.0
    )
    assert abs(iono_free - 20000000.0) < 5.0, f"Expected iono-free ~20000000m, got {iono_free}"
    print(f"[PASS] NavIC L5/S iono-free pseudorange: {iono_free:.2f}m (mitigated tropical ionospheric scintillation)")

    # 4. NavIC 31-Byte Binary Telemetry Packet Packing & Unpacking
    packet_bytes = NavICEngine.pack_telemetry_packet(
        msg_id=1,
        seq_num=4092,
        epoch_timestamp=1726500000,
        latitude=19.0142,
        longitude=72.8427,
        altitude_msl_cm=420,
        sog_cm_s=1111, # ~40 km/h
        cog_tenth_deg=1800, # 180.0 deg
        fix_type=3,
        num_sats=9,
        dop_q4_4=20, # 1.25 DOP
        vehicle_type=3, # HEAVY_TRUCK
        battery_pct=92
    )
    assert len(packet_bytes) == 31, f"Expected 31-byte packet, got {len(packet_bytes)}"

    unpacked = NavICEngine.unpack_telemetry_packet(packet_bytes)
    assert unpacked["crc32_verified"] is True
    assert unpacked["seq_num"] == 4092
    assert abs(unpacked["latitude"] - 19.0142) < 0.001
    assert abs(unpacked["longitude"] - 72.8427) < 0.001
    print(f"[PASS] NavIC 31-byte telemetry packet: packed & verified with hardware CRC32 (seq={unpacked['seq_num']})")

    # 5. Low-Bandwidth 140-Byte Binary SMS Evacuation Protocol
    sms_steps = [
        {"action_code": 1, "distance_m": 250, "bearing_deg": 10, "max_wading_cm": 4},
        {"action_code": 2, "distance_m": 600, "bearing_deg": 90, "max_wading_cm": 14},
        {"action_code": 4, "distance_m": 180, "bearing_deg": 40, "max_wading_cm": 0}
    ]
    raw_sms = SMSFallbackProtocol.encode_evacuation_sms(
        mission_id=8842,
        target_lat=19.0250,
        target_lon=72.8570,
        steps=sms_steps
    )
    assert len(raw_sms) == 140, f"Expected 140 bytes SMS frame, got {len(raw_sms)}"

    decoded_sms = SMSFallbackProtocol.decode_evacuation_sms(raw_sms)
    assert decoded_sms["crc8_valid"] is True
    assert decoded_sms["mission_id"] == 8842
    assert decoded_sms["step_count"] == 3
    assert decoded_sms["steps"][1]["distance_m"] == 600
    print(f"[PASS] 140-byte Binary SMS evacuation frame: Dallas CRC-8 verified, {decoded_sms['step_count']} routing vectors unpacked")

    # 6. Interactive USSD Menu String
    ussd_str = SMSFallbackProtocol.generate_ussd_menu(
        shelter_name="Khalsa Relief Complex",
        distance_km=1.4,
        step_descriptions=[
            "Walk NORTH 250m to Dr Ambedkar Rd",
            "Turn RIGHT onto Highway (Water 14cm)",
            "Reach Shelter Camp on High Ground"
        ]
    )
    assert len(ussd_str) <= 160, f"USSD exceeded 160 char limit: {len(ussd_str)}"
    print(f"[PASS] USSD interactive string ({len(ussd_str)} chars <= 160 chars frame): {ussd_str[:60]}...")

    # 7. REST API: /api/v1/route/safe - Normal Passage
    route_resp = client.post("/api/v1/route/safe", json={
        "request_id": "TEST-REQ-001",
        "vehicle_profile": {
            "classification": "SUV_LCV",
            "ground_clearance_mm": 240,
            "wading_depth_max_mm": 450
        },
        "origin": {"latitude": 19.0195, "longitude": 72.8436},  # Dadar TT
        "destination": {"latitude": 19.0028, "longitude": 72.8429}, # KEM Hospital
        "water_depth_override_m": {"hindmata_junction": 0.20}
    })
    assert route_resp.status_code == 200, f"Route API failed: {route_resp.text}"
    route_data = route_resp.json()
    assert route_data["status"] == "ROUTE_FOUND"
    assert len(route_data["geometry"]["coordinates"]) >= 2
    print(f"[PASS] /api/v1/route/safe: distance={route_data['summary']['total_distance_m']}m, duration={route_data['summary']['estimated_duration_s']}s")

    # 8. REST API: /api/v1/route/safe - Flood Isolation Diagnostics (RFC 7807)
    # Severe flood blocking sedan across all paths (Hindmata=60cm, Tilak=blocked)
    blocked_resp = client.post("/api/v1/route/safe", json={
        "request_id": "TEST-REQ-BLOCKED",
        "vehicle_profile": {
            "classification": "SEDAN",
            "ground_clearance_mm": 160,
            "wading_depth_max_mm": 250
        },
        "origin": {"latitude": 19.0195, "longitude": 72.8436}, # Dadar TT
        "destination": {"latitude": 19.0142, "longitude": 72.8427}, # Hindmata underpass (isolated by 85cm water)
        "water_depth_override_m": {
            "hindmata_junction": 0.85,
            "dadar_tt_circle": 0.35,
            "parel_tt": 0.35
        }
    })
    assert blocked_resp.status_code == 422, f"Expected 422 for blocked route, got {blocked_resp.status_code}"
    prob_details = blocked_resp.json()
    assert prob_details["error_code"] == "ERR_NAV_ROUTING_FLOOD_ISOLATION"
    assert "diagnostics" in prob_details
    print(f"[PASS] /api/v1/route/safe (RFC 7807 422 Problem Details): {prob_details['title']}")

    # 9. REST API: /api/v1/evacuation/nearest-shelter
    shelter_resp = client.post("/api/v1/evacuation/nearest-shelter", json={
        "cohort_id": "COHORT-DADAR-EAST-02",
        "current_centroid": {"latitude": 19.0142, "longitude": 72.8427, "elevation_msl_m": 4.2},
        "demographics": {
            "total_individuals": 120,
            "critical_medical_patients": 2,
            "mobility_impaired_count": 8,
            "infants_children_count": 22
        },
        "transit_capability": {
            "primary_mode": "WALKING_EVACUATION",
            "effective_clearance_mm": 150.0,
            "max_walking_range_m": 3500.0
        },
        "required_facilities": ["HIGH_DEPENDENCY_MEDICAL", "DRINKING_WATER_PURIFICATION"]
    })
    assert shelter_resp.status_code == 200, f"Shelter API error: {shelter_resp.text}"
    shelter_data = shelter_resp.json()
    assert shelter_data["allocation_status"] == "SHELTER_ALLOCATED"
    assert shelter_data["allocated_shelter"]["name"] == "Khalsa College Relief Complex"
    print(f"[PASS] /api/v1/evacuation/nearest-shelter: allocated '{shelter_data['allocated_shelter']['name']}' (ticket: {shelter_data['reservation_ticket']})")

    # 10. REST API: Green Corridor Reservation & Traffic Eviction
    green_resp = client.post("/api/v1/corridor/reserve-green", json={
        "mission_id": "MISSION-NDRF-05-RELIEF",
        "reserved_edge_ids": ["e_dadar_tilak", "e_tilak_senapati"],
        "active": True
    })
    assert green_resp.status_code == 200
    assert green_resp.json()["status"] == "GREEN_CORRIDOR_ACTIVE"
    print("[PASS] /api/v1/corridor/reserve-green: mission corridor active with ITMS signal preemption")

    # Release green corridor
    client.post("/api/v1/corridor/reserve-green", json={
        "mission_id": "MISSION-NDRF-05-RELIEF",
        "reserved_edge_ids": [],
        "active": False
    })

    # 11. REST API: Strategic Asset Corridor Status
    corridor_resp = client.get("/api/v1/corridor/status")
    assert corridor_resp.status_code == 200
    corridors = corridor_resp.json()["corridors"]
    assert len(corridors) > 0
    print(f"[PASS] /api/v1/corridor/status: {len(corridors)} arterial expressways monitored with ultrasonic/CCTV telemetry")

    # 12. REST API: ERSS 112 CAD Automated Incident Ingestion & Dispatch
    erss_resp = client.post("/api/v1/erss/cad-incident", json={
        "incident_id": "CAD-ERSS-112-2026-MUM-8841",
        "caller_phone": "+91-9820011223",
        "latitude": 19.0142,
        "longitude": 72.8427,
        "elevation_msl_m": 4.2,
        "reported_water_depth_cm": 75.0,
        "stranded_persons": 4
    })
    assert erss_resp.status_code == 200
    cad_data = erss_resp.json()
    assert cad_data["erss_cad_status"] == "DISPATCH_INJECTED"
    assert cad_data["vehicle_class"] == "HEAVY_TRUCK"
    print(f"[PASS] /api/v1/erss/cad-incident: dispatched {cad_data['recommended_tactical_unit']} ({cad_data['vehicle_class']})")

    # 13. REST API: NavIC Packet Encoding & Decoding Endpoints
    encode_resp = client.post("/api/v1/navic/telemetry-packet/encode", json={
        "msg_id": 2,
        "seq_num": 55,
        "latitude": 19.0760,
        "longitude": 72.8777,
        "altitude_msl_cm": 850,
        "sog_cm_s": 500,
        "cog_tenth_deg": 2700,
        "fix_type": 3,
        "num_sats": 10,
        "dop_q4_4": 16,
        "vehicle_type": 1,
        "battery_pct": 88
    })
    assert encode_resp.status_code == 200
    encoded_b64 = encode_resp.json()["packet_base64"]

    decode_resp = client.post("/api/v1/navic/telemetry-packet/decode", json={"packet_base64": encoded_b64})
    assert decode_resp.status_code == 200
    assert decode_resp.json()["seq_num"] == 55
    print("[PASS] /api/v1/navic/telemetry-packet/encode & decode verified via REST endpoints")

    print("\nAll Phase 4 Smart Navigation tests passed successfully!")

if __name__ == "__main__":
    test_phase4_all()
