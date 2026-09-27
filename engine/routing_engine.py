import networkx as nx
from typing import Dict, Any, List
from .neighborhood_data import NODES, EDGES

# Emergency routing engine for flooded South-Central Mumbai corridors (Dadar, Parel, Wadala).
# Vehicle clearance limits based on mechanical tolerances:
# - Ambulance: 15cm max (low floor + exhaust pipe water ingress stalls engine)
# - Standard Car/Taxi: 15cm max (risk of electrical short & catalytic converter thermal shock)
# - NDRF / Fire Heavy Rescue: 50cm (elevated snorkel air intake & high differentials)
# - Pedestrian: 12cm (critical: BMC opens storm manholes during floods; high risk of falling in)
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
        # Load road intersection nodes with ground elevations
        for nd in NODES:
            self.base_graph.add_node(
                nd["id"],
                name=nd["name"],
                lat=nd["lat"],
                lon=nd["lon"],
                elevation_m=nd["elevation_m"]
            )

        # Build directed road segments: free-flow transit time = dist / speed
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

        # 1. Standard GPS shortest path (free-flow, ignores flood depth)
        try:
            std_nodes = nx.shortest_path(self.base_graph, source=start_id, target=end_id, weight="base_time_sec")
            std_result = self._build_path_summary(std_nodes, current_node_depths, v_factor)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            std_result = {"status": "NO_PATH"}

        # 2. FloodGuard Safe Route: dynamically prune edges submerged above vehicle clearance
        dry_graph = nx.DiGraph()
        dry_graph.add_nodes_from(self.base_graph.nodes(data=True))

        for u_node, v_node, attrs in self.base_graph.edges(data=True):
            d_u = current_node_depths.get(u_node, 0.0)
            d_v = current_node_depths.get(v_node, 0.0)

            # Elevated flyovers (Tilak Bridge, Wadala Overpass) remain above water regardless of ground ponding
            is_bridge = attrs.get("is_flyover", False)
            effective_h = 0.0 if is_bridge else max(d_u, d_v)

            # Prune flooded street if water exceeds threshold
            if effective_h > h_clearance:
                continue

            # Slowdown penalty: ~3% time penalty per cm of standing water
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
            # All ground routes are submerged and no flyover link is available
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

            # Segment metrics
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
