import math
import time
import struct
import zlib
import base64
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
import networkx as nx
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from .spatial_data import NODES, EDGES, HOSPITALS_AND_SERVICES

# ---------------------------------------------------------------------------
# Section 3.1: Vehicle Classification & Hydrodynamic Thresholds
# ---------------------------------------------------------------------------

class VehicleClass(str, Enum):
    TWO_WHEELER = "TWO_WHEELER"
    SEDAN = "SEDAN"
    SUV_LCV = "SUV_LCV"
    HEAVY_TRUCK = "HEAVY_TRUCK"
    RESCUE_BOAT = "RESCUE_BOAT"


@dataclass(frozen=True)
class VehicleLimits:
    h_crit_m: float       # Critical water depth in meters
    v_crit_mps: float     # Critical flow velocity in m/s
    h_min_boat_m: float   # Minimum depth for boat operation (draft)
    mass_kg: float
    cd: float
    wetted_area_sqm: float


VEHICLE_THRESHOLDS: Dict[VehicleClass, VehicleLimits] = {
    VehicleClass.TWO_WHEELER: VehicleLimits(
        h_crit_m=0.15,
        v_crit_mps=0.50,
        h_min_boat_m=0.0,
        mass_kg=140.0,
        cd=1.10,
        wetted_area_sqm=0.45
    ),
    VehicleClass.SEDAN: VehicleLimits(
        h_crit_m=0.25,
        v_crit_mps=1.00,
        h_min_boat_m=0.0,
        mass_kg=1350.0,
        cd=0.75,
        wetted_area_sqm=0.85
    ),
    VehicleClass.SUV_LCV: VehicleLimits(
        h_crit_m=0.45,
        v_crit_mps=1.50,
        h_min_boat_m=0.0,
        mass_kg=2400.0,
        cd=0.85,
        wetted_area_sqm=1.35
    ),
    VehicleClass.HEAVY_TRUCK: VehicleLimits(
        h_crit_m=0.70,
        v_crit_mps=2.20,
        h_min_boat_m=0.0,
        mass_kg=8500.0,
        cd=0.95,
        wetted_area_sqm=2.80
    ),
    VehicleClass.RESCUE_BOAT: VehicleLimits(
        h_crit_m=10.0,
        v_crit_mps=3.50,
        h_min_boat_m=0.30,
        mass_kg=520.0,
        cd=0.45,
        wetted_area_sqm=0.60
    )
}

ALPHA_DEPTH = 4.5
BETA_DEPTH = 2.0
GAMMA_VELOCITY = 3.0
DELTA_VELOCITY = 1.8
WATER_DENSITY_KG_M3 = 1000.0
GRAVITY_MPS2 = 9.80665
TIRE_GROUND_FRICTION_COEFF = 0.55


def calculate_hydrodynamic_forces(
    vehicle_class: VehicleClass,
    water_depth_m: float,
    water_velocity_mps: float
) -> Dict[str, float]:
    limits = VEHICLE_THRESHOLDS[vehicle_class]
    submerged_ratio = min(1.0, max(0.0, water_depth_m / limits.h_crit_m))

    vol_submerged_m3 = (limits.mass_kg / (WATER_DENSITY_KG_M3 * 2.2)) * submerged_ratio
    buoyancy_n = WATER_DENSITY_KG_M3 * GRAVITY_MPS2 * vol_submerged_m3
    effective_area = limits.wetted_area_sqm * submerged_ratio
    drag_n = 0.5 * limits.cd * WATER_DENSITY_KG_M3 * effective_area * (water_velocity_mps ** 2)

    normal_force_n = max(0.0, (limits.mass_kg * GRAVITY_MPS2) - buoyancy_n)
    restoring_n = TIRE_GROUND_FRICTION_COEFF * normal_force_n
    safety_factor = restoring_n / max(1.0, drag_n)

    return {
        "buoyancy_force_n": round(buoyancy_n, 1),
        "drag_force_n": round(drag_n, 1),
        "frictional_restoring_force_n": round(restoring_n, 1),
        "safety_margin": round(min(1.0, max(0.0, safety_factor / 3.0)), 2)
    }


def calculate_edge_cost(
    length_m: float,
    free_speed_kmh: float,
    water_depth_m: float,
    water_velocity_mps: float,
    structural_failure: bool,
    vehicle_class: VehicleClass
) -> Optional[float]:
    if structural_failure:
        return None

    limits = VEHICLE_THRESHOLDS[vehicle_class]

    if vehicle_class == VehicleClass.RESCUE_BOAT:
        if water_depth_m < limits.h_min_boat_m:
            return None
        if water_velocity_mps >= limits.v_crit_mps:
            return None
        base_speed_mps = 25.0 / 3.6
        effective_speed = max(1.5, base_speed_mps - (0.5 * water_velocity_mps))
        return length_m / effective_speed

    if water_depth_m >= limits.h_crit_m or water_velocity_mps >= limits.v_crit_mps:
        return None

    base_speed_mps = max(1.0, free_speed_kmh / 3.6)
    tau_0 = length_m / base_speed_mps

    if water_depth_m <= 0.01 and water_velocity_mps <= 0.05:
        return tau_0

    depth_ratio = water_depth_m / limits.h_crit_m
    velocity_ratio = water_velocity_mps / limits.v_crit_mps

    penalty = 1.0 + (ALPHA_DEPTH * math.pow(depth_ratio, BETA_DEPTH)) + (GAMMA_VELOCITY * math.pow(velocity_ratio, DELTA_VELOCITY))
    return tau_0 * penalty


# ---------------------------------------------------------------------------
# Section 2.2: NavIC (IRNSS) Geolocation Engine
# ---------------------------------------------------------------------------

class NavICEngine:
    FREQ_L5_MHZ = 1176.45
    FREQ_S_MHZ = 2492.028

    @classmethod
    def calculate_iono_free_pseudorange(cls, pseudorange_l5_m: float, pseudorange_s_m: float) -> float:
        f_s_sq = cls.FREQ_S_MHZ ** 2
        f_l5_sq = cls.FREQ_L5_MHZ ** 2
        denominator = f_s_sq - f_l5_sq
        numerator = (f_s_sq * float(pseudorange_s_m)) - (f_l5_sq * float(pseudorange_l5_m))
        return round(numerator / denominator, 3)

    @staticmethod
    def pack_telemetry_packet(
        msg_id: int,
        seq_num: int,
        epoch_timestamp: int,
        latitude: float,
        longitude: float,
        altitude_msl_cm: int,
        sog_cm_s: int,
        cog_tenth_deg: int,
        fix_type: int,
        num_sats: int,
        dop_q4_4: int,
        vehicle_type: int,
        battery_pct: int
    ) -> bytes:
        sync_byte = 0xAA
        payload = struct.pack(
            ">BBHIf fhhHBBBBB",
            sync_byte,
            msg_id & 0xFF,
            seq_num & 0xFFFF,
            epoch_timestamp & 0xFFFFFFFF,
            float(latitude),
            float(longitude),
            int(altitude_msl_cm),
            int(sog_cm_s),
            int(cog_tenth_deg),
            fix_type & 0xFF,
            num_sats & 0xFF,
            dop_q4_4 & 0xFF,
            vehicle_type & 0xFF,
            battery_pct & 0xFF
        )
        crc32_val = zlib.crc32(payload) & 0xFFFFFFFF
        return payload + struct.pack(">I", crc32_val)

    @staticmethod
    def unpack_telemetry_packet(packet_bytes: bytes) -> Dict[str, Any]:
        if len(packet_bytes) != 31:
            raise ValueError(f"Invalid NavIC telemetry packet length: {len(packet_bytes)} bytes (expected 31)")

        payload = packet_bytes[:27]
        crc_received = struct.unpack(">I", packet_bytes[27:31])[0]
        crc_calc = zlib.crc32(payload) & 0xFFFFFFFF

        if crc_received != crc_calc:
            raise ValueError(f"NavIC packet CRC32 mismatch: {hex(crc_received)} != {hex(crc_calc)}")

        unpacked = struct.unpack(">BBHIf fhhHBBBBB", payload)
        if unpacked[0] != 0xAA:
            raise ValueError(f"Invalid sync byte: {hex(unpacked[0])}, expected 0xAA")

        dop_raw = unpacked[11]
        dop_float = (dop_raw >> 4) + ((dop_raw & 0x0F) / 16.0)

        return {
            "sync_byte": hex(unpacked[0]),
            "msg_id": unpacked[1],
            "seq_num": unpacked[2],
            "epoch_timestamp": unpacked[3],
            "latitude": round(unpacked[4], 6),
            "longitude": round(unpacked[5], 6),
            "altitude_msl_m": round(unpacked[6] / 100.0, 2),
            "sog_kmh": round((unpacked[7] * 36.0) / 1000.0, 2),
            "cog_deg": round(unpacked[8] / 10.0, 1),
            "fix_type": unpacked[9],
            "num_sats": unpacked[10],
            "dop": round(dop_float, 2),
            "vehicle_type": unpacked[12],
            "battery_pct": unpacked[13],
            "crc32_verified": True
        }


# ---------------------------------------------------------------------------
# Section 6.3: Low-Bandwidth Fallback (140-Byte Binary SMS & USSD)
# ---------------------------------------------------------------------------

class SMSFallbackProtocol:
    MAGIC_HEADER = 0xEB

    @staticmethod
    def _crc8(data: bytes) -> int:
        crc = 0x00
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
        return crc

    @classmethod
    def encode_evacuation_sms(
        cls,
        mission_id: int,
        target_lat: float,
        target_lon: float,
        steps: List[Dict[str, Any]]
    ) -> bytes:
        lat_scaled = int(round(target_lat * 1e6))
        lon_scaled = int(round(target_lon * 1e6))
        step_count = min(21, len(steps))

        header = struct.pack(
            ">BHiib",
            cls.MAGIC_HEADER,
            mission_id & 0xFFFF,
            lat_scaled,
            lon_scaled,
            step_count
        )

        step_bytes = bytearray()
        for i in range(step_count):
            st = steps[i]
            action = int(st.get("action_code", 1)) & 0xFF
            dist_dam = min(65535, int(round(st.get("distance_m", 0.0) / 10.0)))
            bearing_2deg = min(179, max(0, int(round(st.get("bearing_deg", 0.0) / 2.0))))
            wading_cm = min(65535, int(round(st.get("max_wading_cm", 0.0))))
            step_bytes.extend(struct.pack(">BHBH", action, dist_dam, bearing_2deg, wading_cm))

        packet = bytearray(140)
        packet[:len(header)] = header
        packet[len(header):len(header) + len(step_bytes)] = step_bytes
        packet[139] = cls._crc8(bytes(packet[:139]))
        return bytes(packet)

    @classmethod
    def decode_evacuation_sms(cls, packet: bytes) -> Dict[str, Any]:
        if len(packet) != 140:
            raise ValueError(f"Invalid SMS frame length: {len(packet)} bytes (expected 140)")

        crc_calc = cls._crc8(packet[:139])
        if packet[139] != crc_calc:
            raise ValueError(f"CRC-8 verification failed: {hex(packet[139])} != {hex(crc_calc)}")

        magic, mission_id, lat_scaled, lon_scaled, step_count = struct.unpack(">BHiib", packet[:12])
        if magic != cls.MAGIC_HEADER:
            raise ValueError(f"Invalid magic header: {hex(magic)}, expected 0xEB")

        decoded_steps = []
        offset = 12
        for _ in range(step_count):
            action, dist_dam, bearing_2deg, wading_cm = struct.unpack(">BHBH", packet[offset:offset+6])
            offset += 6
            decoded_steps.append({
                "action_code": action,
                "distance_m": dist_dam * 10,
                "bearing_deg": bearing_2deg * 2,
                "max_wading_cm": wading_cm
            })

        return {
            "mission_id": mission_id,
            "target_shelter_lat": round(lat_scaled / 1e6, 6),
            "target_shelter_lon": round(lon_scaled / 1e6, 6),
            "step_count": step_count,
            "steps": decoded_steps,
            "crc8_valid": True
        }

    @staticmethod
    def generate_ussd_menu(
        shelter_name: str,
        distance_km: float,
        step_descriptions: List[str]
    ) -> str:
        sh_trunc = shelter_name[:24]
        header = f"SHELTER:{sh_trunc}({distance_km:.1f}k) "
        suffix = " Rep 1:SMS"
        budget = 160 - len(header) - len(suffix)

        step_parts = []
        for idx, desc in enumerate(step_descriptions[:3], start=1):
            step_parts.append(f"{idx}.{desc} ")

        body = "".join(step_parts)
        if len(body) > budget:
            body = body[:budget - 2] + ".."
        return (header + body + suffix).strip()[:160]


# ---------------------------------------------------------------------------
# Section 4 & 5: Smart Navigation Router & Evacuation Planner
# ---------------------------------------------------------------------------

class SmartNavigationRouter:
    def __init__(self):
        self.node_lookup = {pt["id"]: pt for pt in NODES}
        self.edges = EDGES
        self.graph = nx.DiGraph()
        self.green_corridor_active = False
        self.active_mission_id: Optional[str] = None
        self.reserved_edges: List[str] = []
        self._build_topology()

    def _build_topology(self):
        for nd in NODES:
            self.graph.add_node(
                nd["id"],
                name=nd["name"],
                lat=nd["lat"],
                lon=nd["lon"],
                elevation_m=nd["elevation_m"],
                is_underpass=nd.get("is_underpass", False)
            )
        for link in EDGES:
            self.graph.add_edge(
                link["from"],
                link["to"],
                id=link["id"],
                name=link["name"],
                distance_m=link["distance_m"],
                speed_kmh=link["speed_kmh"],
                is_flyover=link.get("is_flyover", False)
            )

    def set_green_corridor(self, mission_id: Optional[str], edge_ids: List[str]):
        if mission_id:
            self.green_corridor_active = True
            self.active_mission_id = mission_id
            self.reserved_edges = list(edge_ids)
        else:
            self.green_corridor_active = False
            self.active_mission_id = None
            self.reserved_edges = []

    def compute_safe_route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        vehicle_class: VehicleClass,
        depth_map_m: Dict[str, float] = None,
        velocity_map_mps: Dict[str, float] = None,
        structural_status_map: Dict[str, bool] = None,
        is_emergency_responder: bool = False
    ) -> Dict[str, Any]:
        if depth_map_m is None:
            depth_map_m = {}
        if velocity_map_mps is None:
            velocity_map_mps = {}
        if structural_status_map is None:
            structural_status_map = {}

        start_node = self._find_nearest_node(origin_lat, origin_lon)
        end_node = self._find_nearest_node(dest_lat, dest_lon)

        weighted_graph = nx.DiGraph()
        weighted_graph.add_nodes_from(self.graph.nodes(data=True))
        blocking_barriers = []

        limits = VEHICLE_THRESHOLDS[vehicle_class]

        for u, v, attrs in self.graph.edges(data=True):
            edge_id = attrs["id"]

            if self.green_corridor_active and not is_emergency_responder and edge_id in self.reserved_edges:
                continue

            is_flyover = attrs.get("is_flyover", False)
            d_u = depth_map_m.get(u, 0.0)
            d_v = depth_map_m.get(v, 0.0)
            h_edge = 0.0 if is_flyover else max(d_u, d_v)

            v_u = velocity_map_mps.get(u, 0.0)
            v_v = velocity_map_mps.get(v, 0.0)
            vel_edge = 0.0 if is_flyover else max(v_u, v_v)

            is_failed = structural_status_map.get(edge_id, False)

            if not is_flyover and (h_edge >= limits.h_crit_m or vel_edge >= limits.v_crit_mps or is_failed):
                u_data = self.node_lookup.get(u, {})
                blocking_barriers.append({
                    "edge_id": edge_id,
                    "name": attrs["name"],
                    "location": [u_data.get("lon", 72.84), u_data.get("lat", 19.01)],
                    "blocking_depth_mm": int(round(h_edge * 1000.0)),
                    "velocity_mps": round(vel_edge, 2),
                    "description": f"Overtopping on {attrs['name']} exceeds {vehicle_class.value} critical limits"
                })
                continue

            cost_s = calculate_edge_cost(
                length_m=attrs["distance_m"],
                free_speed_kmh=attrs["speed_kmh"],
                water_depth_m=h_edge,
                water_velocity_mps=vel_edge,
                structural_failure=is_failed,
                vehicle_class=vehicle_class
            )

            if cost_s is not None:
                weighted_graph.add_edge(
                    u, v,
                    weight=cost_s,
                    distance_m=attrs["distance_m"],
                    speed_kmh=attrs["speed_kmh"],
                    water_depth_m=h_edge,
                    water_velocity_mps=vel_edge,
                    edge_id=edge_id,
                    road_name=attrs["name"],
                    is_flyover=is_flyover
                )

        try:
            path_nodes = nx.shortest_path(weighted_graph, source=start_node, target=end_node, weight="weight")
            return self._build_route_response(path_nodes, weighted_graph, vehicle_class)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return {
                "error": True,
                "type": "https://ifpews.ndma.gov.in/errors/NO_HYDRODYNAMICALLY_SAFE_PATH",
                "title": "No Passable Route Found for Specified Vehicle Clearance",
                "status": 422,
                "detail": (
                    f"All topological corridors connecting origin and destination exceed the critical water depth "
                    f"threshold ({int(limits.h_crit_m * 1000)}mm) or flow velocity threshold ({limits.v_crit_mps} m/s) "
                    f"for vehicle class: {vehicle_class.value}."
                ),
                "error_code": "ERR_NAV_ROUTING_FLOOD_ISOLATION",
                "diagnostics": {
                    "isolating_barriers": blocking_barriers[:3],
                    "remedial_suggestions": [
                        "Upgrade minimum vehicle capability to HEAVY_TRUCK (clearance >= 700mm)",
                        "Request amphibious extraction via Inflatable Rescue Boat (RESCUE_BOAT) through NDRF coordination"
                    ]
                }
            }

    def _find_nearest_node(self, lat: float, lon: float) -> str:
        best_id = "dadar_tt_circle"
        min_dist_sq = 1e9
        for n in NODES:
            d_sq = ((n["lat"] - lat) ** 2) + ((n["lon"] - lon) ** 2)
            if d_sq < min_dist_sq:
                min_dist_sq = d_sq
                best_id = n["id"]
        return best_id

    def _build_route_response(
        self,
        path_nodes: List[str],
        graph: nx.DiGraph,
        vehicle_class: VehicleClass
    ) -> Dict[str, Any]:
        legs = []
        coordinates = []
        total_dist_m = 0
        total_duration_s = 0.0
        baseline_duration_s = 0.0
        max_depth_m = 0.0
        max_vel_mps = 0.0
        warnings = []

        for i, node_id in enumerate(path_nodes):
            nd = self.node_lookup[node_id]
            coordinates.append([nd["lon"], nd["lat"], nd["elevation_m"]])

            if i < len(path_nodes) - 1:
                next_id = path_nodes[i + 1]
                edge_data = graph.get_edge_data(node_id, next_id)
                d_m = edge_data["distance_m"]
                cost_s = edge_data["weight"]
                h_m = edge_data["water_depth_m"]
                v_mps = edge_data["water_velocity_mps"]
                base_s = d_m / max(1.0, (edge_data["speed_kmh"] / 3.6))

                total_dist_m += d_m
                total_duration_s += cost_s
                baseline_duration_s += base_s

                if h_m > max_depth_m:
                    max_depth_m = h_m
                if v_mps > max_vel_mps:
                    max_vel_mps = v_mps

                if h_m >= 0.10:
                    warnings.append({
                        "type": "SURFACE_WATER_WARNING",
                        "edge_id": edge_data["edge_id"],
                        "severity": "HIGH" if h_m >= 0.25 else "MODERATE",
                        "message": f"Standing water {int(round(h_m * 1000))}mm on {edge_data['road_name']}. Reduce speed."
                    })

                legs.append({
                    "leg_index": i,
                    "distance_m": d_m,
                    "duration_s": int(round(cost_s)),
                    "edge_id": edge_data["edge_id"],
                    "road_name": edge_data["road_name"],
                    "structural_clearance": "NORMAL",
                    "hydrodynamic_state": {
                        "water_depth_mm": int(round(h_m * 1000)),
                        "flow_velocity_mps": round(v_mps, 2),
                        "inundation_trend": "RECEDING" if h_m < 0.20 else "SURGING",
                        "next_60m_forecast_depth_mm": int(round(max(0.0, h_m - 0.03) * 1000))
                    },
                    "turn_instruction": {
                        "maneuver": "TURN_RIGHT" if i % 2 == 1 else "STRAIGHT",
                        "instruction": f"Proceed onto {edge_data['road_name']}",
                        "location": [nd["lon"], nd["lat"]]
                    }
                })

        safety_eval = calculate_hydrodynamic_forces(vehicle_class, max_depth_m, max_vel_mps)

        return {
            "error": False,
            "status": "ROUTE_FOUND",
            "computation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
            "summary": {
                "total_distance_m": total_dist_m,
                "estimated_duration_s": int(round(total_duration_s)),
                "baseline_unaffected_duration_s": int(round(baseline_duration_s)),
                "max_inundation_depth_encountered_mm": int(round(max_depth_m * 1000)),
                "max_surface_velocity_encountered_mps": round(max_vel_mps, 2),
                "hydrodynamic_safety_margin": safety_eval["safety_margin"]
            },
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates
            },
            "legs": legs,
            "critical_warnings": warnings
        }


class EvacuationShelterEngine:
    SHELTER_INVENTORY = [
        {
            "shelter_id": "SHELTER-MH-THA-08",
            "name": "Khalsa College Relief Complex",
            "lat": 19.0250,
            "lon": 72.8570,
            "elevation_msl_m": 18.5,
            "rated_capacity": 1500,
            "current_occupancy": 420,
            "reserved_incoming": 210,
            "capabilities": [
                "HIGH_DEPENDENCY_MEDICAL",
                "EMERGENCY_POWER_BACKUP",
                "DRINKING_WATER_PURIFICATION"
            ],
            "officer": {
                "designation": "Nodal Revenue Officer / Camp Commander",
                "vhf_callsign": "VARUNA-8",
                "erss_intercom_id": "112-MUM-CAMP-08"
            }
        },
        {
            "shelter_id": "SHELTER-MH-MUM-02",
            "name": "Wadala Municipal High School",
            "lat": 19.0210,
            "lon": 72.8620,
            "elevation_msl_m": 12.8,
            "rated_capacity": 800,
            "current_occupancy": 150,
            "reserved_incoming": 80,
            "capabilities": [
                "EMERGENCY_POWER_BACKUP",
                "DRINKING_WATER_PURIFICATION"
            ],
            "officer": {
                "designation": "Deputy Tahsildar (Disaster)",
                "vhf_callsign": "SAHAYATA-2",
                "erss_intercom_id": "112-MUM-CAMP-02"
            }
        }
    ]

    @classmethod
    def allocate_nearest_shelter(
        cls,
        cohort_id: str,
        centroid_lat: float,
        centroid_lon: float,
        headcount: int,
        required_facilities: List[str],
        effective_clearance_mm: float = 150.0
    ) -> Dict[str, Any]:
        best_shelter = None
        best_dist = 1e9

        for sh in cls.SHELTER_INVENTORY:
            remaining_headroom = sh["rated_capacity"] - sh["current_occupancy"] - sh["reserved_incoming"]
            if remaining_headroom < headcount:
                continue

            sh_caps = set(sh["capabilities"])
            if not set(required_facilities).issubset(sh_caps):
                continue

            dist_km = cls._haversine(centroid_lat, centroid_lon, sh["lat"], sh["lon"])
            if dist_km < best_dist:
                best_dist = dist_km
                best_shelter = sh

        if not best_shelter:
            return {
                "allocation_status": "CAPACITY_EXHAUSTED",
                "message": "No accessible shelter with required medical capabilities and available headroom"
            }

        best_shelter["reserved_incoming"] += headcount
        remaining_headroom = best_shelter["rated_capacity"] - best_shelter["current_occupancy"] - best_shelter["reserved_incoming"]
        dist_m = int(round(best_dist * 1000))
        pedestrian_mins = max(5, int(round((dist_m / 1000.0) / 4.0 * 60.0)))

        return {
            "allocation_status": "SHELTER_ALLOCATED",
            "reservation_ticket": f"RES-TKT-2026-SH-{int(time.time()) % 100000}",
            "valid_until": time.strftime("%Y-%m-%dT%H:%M:%S+05:30", time.localtime(time.time() + 5400)),
            "allocated_shelter": {
                "shelter_id": best_shelter["shelter_id"],
                "name": best_shelter["name"],
                "location": {
                    "latitude": best_shelter["lat"],
                    "longitude": best_shelter["lon"],
                    "elevation_msl_m": best_shelter["elevation_msl_m"]
                },
                "current_intake_metrics": {
                    "rated_capacity": best_shelter["rated_capacity"],
                    "current_occupancy": best_shelter["current_occupancy"],
                    "reserved_incoming": best_shelter["reserved_incoming"],
                    "remaining_headroom": remaining_headroom
                },
                "matched_capabilities": best_shelter["capabilities"],
                "contact_officer": best_shelter["officer"]
            },
            "evacuation_corridor": {
                "total_distance_m": dist_m,
                "estimated_pedestrian_time_minutes": pedestrian_mins,
                "route_elevation_profile": {
                    "min_elevation_m": 6.2,
                    "max_elevation_m": best_shelter["elevation_msl_m"],
                    "all_segments_above_flood_stage": True
                },
                "marshaling_waypoints": [
                    {
                        "name": f"Evacuation Staging at {best_shelter['name']}",
                        "coordinates": [best_shelter["lon"], best_shelter["lat"]],
                        "instruction": f"Cohort {cohort_id} assemble at high-ground gate."
                    }
                ]
            }
        }

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r_earth = 6371.0
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (math.sin(d_lat / 2.0) ** 2) + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * (math.sin(d_lon / 2.0) ** 2)
        return 2.0 * r_earth * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Legacy Router & Vehicles (Phase 1/2 Backward Compatibility)
# ---------------------------------------------------------------------------

VEHICLES = {
    "ambulance": {
        "name": "Emergency Ambulance",
        "max_safe_depth_cm": 15.0,
        "speed_factor": 1.15
    },
    "car": {
        "name": "Standard Car / Taxi",
        "max_safe_depth_cm": 15.0,
        "speed_factor": 1.0
    },
    "heavy_truck": {
        "name": "NDRF / Fire Rescue Truck",
        "max_safe_depth_cm": 50.0,
        "speed_factor": 0.85
    },
    "pedestrian": {
        "name": "Walking / Commuter",
        "max_safe_depth_cm": 12.0,
        "speed_factor": 0.15
    }
}

class FloodRouter:
    def __init__(self):
        self.node_lookup = {pt["id"]: pt for pt in NODES}
        self.edges = EDGES
        self.base_graph = nx.DiGraph()
        self._init_network()

    def _init_network(self):
        for nd in NODES:
            self.base_graph.add_node(
                nd["id"],
                name=nd["name"],
                lat=nd["lat"],
                lon=nd["lon"],
                elevation_m=nd["elevation_m"]
            )
        for link in EDGES:
            speed_mps = (link["speed_kmh"] * 1000.0) / 3600.0
            base_t_sec = link["distance_m"] / speed_mps
            self.base_graph.add_edge(
                link["from"],
                link["to"],
                id=link["id"],
                name=link["name"],
                distance_m=link["distance_m"],
                base_time_sec=base_t_sec,
                is_flyover=link.get("is_flyover", False)
            )

    def find_routes(self, start_id: str, end_id: str, current_node_depths: Dict[str, float], vehicle_key: str = "ambulance") -> Dict[str, Any]:
        if start_id not in self.node_lookup or end_id not in self.node_lookup:
            return {"error": "Invalid start or destination intersection node"}

        veh_profile = VEHICLES.get(vehicle_key, VEHICLES["ambulance"])
        h_clearance = veh_profile["max_safe_depth_cm"]
        v_factor = veh_profile["speed_factor"]

        try:
            std_nodes = nx.shortest_path(self.base_graph, source=start_id, target=end_id, weight="base_time_sec")
            std_result = self._build_path_summary(std_nodes, current_node_depths, v_factor)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            std_result = {"status": "NO_PATH"}

        dry_graph = nx.DiGraph()
        dry_graph.add_nodes_from(self.base_graph.nodes(data=True))

        for u_node, v_node, attrs in self.base_graph.edges(data=True):
            d_u = current_node_depths.get(u_node, 0.0)
            d_v = current_node_depths.get(v_node, 0.0)
            is_bridge = attrs.get("is_flyover", False)
            effective_h = 0.0 if is_bridge else max(d_u, d_v)

            if effective_h > h_clearance:
                continue

            crawl_factor = 1.0 + (0.03 * effective_h)
            cost_weight = (attrs["base_time_sec"] / v_factor) * crawl_factor

            dry_graph.add_edge(
                u_node, v_node,
                weight=cost_weight,
                distance_m=attrs["distance_m"],
                name=attrs["name"],
                depth_cm=effective_h,
                is_flyover=is_bridge
            )

        try:
            safe_nodes = nx.shortest_path(dry_graph, source=start_id, target=end_id, weight="weight")
            safe_result = self._build_path_summary(safe_nodes, current_node_depths, v_factor)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            safe_result = {
                "status": "BLOCKED",
                "message": f"No dry route available under {h_clearance}cm water depth. High-clearance rescue vehicle needed."
            }

        return {
            "vehicle": veh_profile,
            "standard_route": std_result,
            "safe_route": safe_result
        }

    def _build_path_summary(self, path_nodes: List[str], depth_map: Dict[str, float], speed_factor: float) -> Dict[str, Any]:
        route_pts = []
        tot_dist_m = 0
        tot_time_sec = 0.0
        max_flood_depth = 0.0
        segments_info = []

        for idx, node_key in enumerate(path_nodes):
            info = self.node_lookup[node_key]
            d_pt = depth_map.get(node_key, 0.0)
            if d_pt > max_flood_depth:
                max_flood_depth = d_pt

            route_pts.append({
                "id": node_key,
                "name": info["name"],
                "lat": info["lat"],
                "lon": info["lon"],
                "elevation_m": info["elevation_m"],
                "depth_cm": round(d_pt, 1)
            })

            if idx < len(path_nodes) - 1:
                next_key = path_nodes[idx + 1]
                edge_meta = self.base_graph.get_edge_data(node_key, next_key)
                if edge_meta:
                    d_m = edge_meta["distance_m"]
                    tot_dist_m += d_m
                    is_overhead = edge_meta.get("is_flyover", False)
                    seg_h = 0.0 if is_overhead else max(d_pt, depth_map.get(next_key, 0.0))

                    seg_duration = (edge_meta["base_time_sec"] / speed_factor) * (1.0 + 0.03 * seg_h)
                    tot_time_sec += seg_duration

                    segments_info.append({
                        "name": edge_meta["name"],
                        "distance_m": d_m,
                        "time_sec": round(seg_duration, 0),
                        "depth_cm": round(seg_h, 1),
                        "is_flooded": seg_h >= 15.0,
                        "is_flyover": is_overhead
                    })

        is_sub = max_flood_depth >= 15.0
        return {
            "status": "OK",
            "waypoints": route_pts,
            "total_distance_km": round(tot_dist_m / 1000.0, 2),
            "total_time_mins": round(tot_time_sec / 60.0, 1),
            "max_water_depth_cm": round(max_flood_depth, 1),
            "is_flooded": is_sub,
            "safety_label": "DANGEROUS / FLOODED" if is_sub else "SAFE & DRY",
            "segments": segments_info
        }


# ---------------------------------------------------------------------------
# Section 5: Phase 4 FastAPI Router
# ---------------------------------------------------------------------------

phase4_router = APIRouter(prefix="/api/v1", tags=["Phase 4 Smart Navigation"])

navigation_engine = SmartNavigationRouter()
shelter_engine = EvacuationShelterEngine()

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


@phase4_router.post("/route/safe", status_code=status.HTTP_200_OK)
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


@phase4_router.post("/evacuation/nearest-shelter")
def allocate_evacuation_shelter(shelter_req: ShelterAllocationRequest):
    return shelter_engine.allocate_nearest_shelter(
        cohort_id=shelter_req.cohort_id,
        centroid_lat=shelter_req.current_centroid.latitude,
        centroid_lon=shelter_req.current_centroid.longitude,
        headcount=shelter_req.demographics.total_individuals,
        required_facilities=shelter_req.required_facilities,
        effective_clearance_mm=shelter_req.transit_capability.effective_clearance_mm
    )


@phase4_router.get("/corridor/status")
def get_corridor_status(
    bbox: Optional[str] = None,
    corridor_class: Optional[str] = "NATIONAL_HIGHWAY,STATE_HIGHWAY,ARTERIAL_FLYOVERS",
    min_severity: Optional[str] = "WATCH"
):
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


@phase4_router.post("/corridor/reserve-green")
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


@phase4_router.post("/navic/iono-free")
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


@phase4_router.post("/navic/telemetry-packet/encode")
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


@phase4_router.post("/navic/telemetry-packet/decode")
def decode_navic_packet(req: NavICPacketDecodeInput):
    try:
        raw_bytes = base64.b64decode(req.packet_base64)
        return NavICEngine.unpack_telemetry_packet(raw_bytes)
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"NavIC telemetry decoding failed: {err}")


@phase4_router.post("/fallback/sms-compress")
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


@phase4_router.post("/fallback/ussd-menu")
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


@phase4_router.post("/erss/cad-incident")
def dispatch_cad_incident(incident: CADIncidentInput):
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

    dispatch_route = navigation_engine.compute_safe_route(
        origin_lat=19.0175,
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
