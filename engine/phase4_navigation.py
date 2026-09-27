import math
import time
import struct
import zlib
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
import networkx as nx

from .neighborhood_data import NODES, EDGES, HOSPITALS_AND_SERVICES

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
    mass_kg: float        # Vehicle mass
    cd: float             # Drag coefficient
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

# Empirical monsoonal drag and depth calibration coefficients (IFPEWS Rev 3.2)
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
    
    # Submerged volume displacement
    vol_submerged_m3 = (limits.mass_kg / (WATER_DENSITY_KG_M3 * 2.2)) * submerged_ratio
    buoyancy_n = WATER_DENSITY_KG_M3 * GRAVITY_MPS2 * vol_submerged_m3
    
    # Lateral hydrodynamic drag force
    effective_area = limits.wetted_area_sqm * submerged_ratio
    drag_n = 0.5 * limits.cd * WATER_DENSITY_KG_M3 * effective_area * (water_velocity_mps ** 2)
    
    # Frictional restoring force
    normal_force_n = max(0.0, (limits.mass_kg * GRAVITY_MPS2) - buoyancy_n)
    restoring_n = TIRE_GROUND_FRICTION_COEFF * normal_force_n
    
    # Hydrodynamic safety factor
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

    # Watercraft navigation regime
    if vehicle_class == VehicleClass.RESCUE_BOAT:
        if water_depth_m < limits.h_min_boat_m:
            return None
        if water_velocity_mps >= limits.v_crit_mps:
            return None
        base_speed_mps = 25.0 / 3.6
        effective_speed = max(1.5, base_speed_mps - (0.5 * water_velocity_mps))
        return length_m / effective_speed

    # Ground vehicles: physical limits threshold
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
    # L5: 1176.45 MHz, S: 2492.028 MHz
    FREQ_L5_MHZ = 1176.45
    FREQ_S_MHZ = 2492.028

    @classmethod
    def calculate_iono_free_pseudorange(cls, pseudorange_l5_m: float, pseudorange_s_m: float) -> float:
        # P_iono_free = (f_S^2 * P_S - f_L5^2 * P_L5) / (f_S^2 - f_L5^2)
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
        # 27-byte header payload
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
        
        # Max steps that fit in 140 bytes: (140 - 1 - 12 - 1) // 6 = 21 steps
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
        
        crc = cls._crc8(bytes(packet[:139]))
        packet[139] = crc
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
    """
    Production-grade routing engine incorporating hydrodynamic edge cost formulation,
    structural integrity triggers, green corridor reservations, and RFC 7807 problem details.
    """
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

        # Spatial snap to nearest network nodes
        start_node = self._find_nearest_node(origin_lat, origin_lon)
        end_node = self._find_nearest_node(dest_lat, dest_lon)

        # Build dynamic time-dependent graph
        weighted_graph = nx.DiGraph()
        weighted_graph.add_nodes_from(self.graph.nodes(data=True))

        blocking_barriers = []

        for u, v, attrs in self.graph.edges(data=True):
            edge_id = attrs["id"]

            # Civilian eviction during active Green Corridor
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

            # Check if this edge would block the vehicle
            limits = VEHICLE_THRESHOLDS[vehicle_class]
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
            # RFC 7807 compliant error diagnostics
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


# ---------------------------------------------------------------------------
# Section 4.1: Capacitated Evacuation Shelter Allocator
# ---------------------------------------------------------------------------

class EvacuationShelterEngine:
    """
    Solves multi-source multi-sink evacuation allocation respecting dynamic
    shelter capacities, medical capabilities, and walking clearance limits.
    """
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

            # Check facility requirements
            sh_caps = set(sh["capabilities"])
            if not set(required_facilities).issubset(sh_caps):
                continue

            # Haversine distance
            dist_km = cls._haversine(centroid_lat, centroid_lon, sh["lat"], sh["lon"])
            if dist_km < best_dist:
                best_dist = dist_km
                best_shelter = sh

        if not best_shelter:
            return {
                "allocation_status": "CAPACITY_EXHAUSTED",
                "message": "No accessible shelter with required medical capabilities and available headroom"
            }

        # Dynamic reservation update
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
