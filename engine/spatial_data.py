# Spatial network datasets and database schema for FloodGuard (South-Central Mumbai)

DB_SCHEMA_SQL = """-- FloodGuard TimescaleDB & PostGIS table definitions

create extension if not exists postgis;
create extension if not exists timescaledb;

-- CWC and local river stage telemetry
create table if not exists telemetry_river_gauges (
    recorded_at timestamptz not null,
    station_code varchar(64) not null,
    agency_source varchar(32) not null,
    water_stage_m_msl double precision not null,
    discharge_cumecs double precision,
    rate_of_rise_m_hr double precision,
    qc_flag integer not null default 0,
    location_geom geometry(Point, 4326) not null,
    metadata jsonb
);

select create_hypertable(
    'telemetry_river_gauges',
    'recorded_at',
    chunk_time_interval => interval '7 days',
    if_not_exists => true
);

create index if not exists idx_river_gauges_time on telemetry_river_gauges (station_code, recorded_at desc);
create index if not exists idx_river_gauges_geom on telemetry_river_gauges using gist (location_geom);

-- IMD radar and satellite precipitation metadata
create table if not exists gridded_rainfall_metadata (
    grid_id uuid primary key default gen_random_uuid(),
    timestamp_epoch timestamptz not null,
    source_sensor varchar(32) not null,
    resolution_m integer not null,
    bounding_box geometry(Polygon, 4326) not null,
    storage_path_uri varchar(256) not null,
    max_intensity_mm_hr double precision,
    mean_intensity_mm_hr double precision,
    checksum_sha256 varchar(64) not null
);

create index if not exists idx_rainfall_grid_time on gridded_rainfall_metadata (timestamp_epoch desc);
create index if not exists idx_rainfall_grid_geom on gridded_rainfall_metadata using gist (bounding_box);

-- BMC municipal drain sensors
create table if not exists municipal_drain_telemetry (
    recorded_at timestamptz not null,
    device_uid varchar(64) not null,
    municipality varchar(64) not null default 'BMC',
    drain_network varchar(64) not null,
    water_stage_depth_m double precision not null,
    freeboard_m double precision not null,
    flow_velocity_m_s double precision,
    sea_tide_height_m double precision,
    qc_flag integer not null default 0,
    location_geom geometry(Point, 4326) not null
);

select create_hypertable(
    'municipal_drain_telemetry',
    'recorded_at',
    chunk_time_interval => interval '7 days',
    if_not_exists => true
);

-- IMD NOWCAST alerts
create table if not exists nowcast_alerts (
    alert_id uuid primary key default gen_random_uuid(),
    identifier varchar(64) not null unique,
    sent_time_utc timestamptz not null,
    valid_until_utc timestamptz not null,
    severity varchar(32) not null,
    hazard_profile varchar(64) not null,
    expected_rain_mm double precision,
    affected_polygon geometry(Polygon, 4326) not null
);
"""

NODES = [
    {
        "id": "hindmata_junction",
        "name": "Hindmata Flyover Underpass",
        "lat": 19.0142,
        "lon": 72.8427,
        "elevation_m": 4.2,
        "catchment_area_sqm": 85000,
        "runoff_c": 0.90,
        "pipe_diameter_m": 0.9,
        "pipe_slope": 0.0012,
        "storage_area_sqm": 7200,
        "is_underpass": True,
        "notes": "Floods rapidly once rain exceeds ~30mm/hr. Major chokepoint on Dr. Ambedkar Road."
    },
    {
        "id": "dadar_tt_circle",
        "name": "Dadar TT Circle (Khodadad Circle)",
        "lat": 19.0195,
        "lon": 72.8436,
        "elevation_m": 5.8,
        "catchment_area_sqm": 72000,
        "runoff_c": 0.88,
        "pipe_diameter_m": 1.1,
        "pipe_slope": 0.0018,
        "storage_area_sqm": 8500,
        "is_underpass": False,
        "notes": "Main junction connecting north and south traffic. Water drains towards Hindmata."
    },
    {
        "id": "kings_circle",
        "name": "King's Circle / Maheshwari Udyan",
        "lat": 19.0285,
        "lon": 72.8550,
        "elevation_m": 3.9,
        "catchment_area_sqm": 95000,
        "runoff_c": 0.92,
        "pipe_diameter_m": 0.95,
        "pipe_slope": 0.0010,
        "storage_area_sqm": 9500,
        "is_underpass": True,
        "notes": "Railway subway depression that historically submerges local train lines."
    },
    {
        "id": "parel_tt",
        "name": "Parel TT Junction",
        "lat": 19.0068,
        "lon": 72.8402,
        "elevation_m": 6.5,
        "catchment_area_sqm": 68000,
        "runoff_c": 0.87,
        "pipe_diameter_m": 1.2,
        "pipe_slope": 0.0025,
        "storage_area_sqm": 6500,
        "is_underpass": False,
        "notes": "Intersection leading directly to the hospital corridor (KEM & Wadia hospitals)."
    },
    {
        "id": "kem_hospital_gate",
        "name": "KEM Hospital Emergency Gate",
        "lat": 19.0035,
        "lon": 72.8424,
        "elevation_m": 7.4,
        "catchment_area_sqm": 42000,
        "runoff_c": 0.82,
        "pipe_diameter_m": 1.1,
        "pipe_slope": 0.003,
        "storage_area_sqm": 5000,
        "is_underpass": False,
        "notes": "Main trauma center entrance on Acharya Donde Marg. Must remain accessible 24/7."
    },
    {
        "id": "wadala_bridge",
        "name": "Wadala Bridge (Elevated Road)",
        "lat": 19.0168,
        "lon": 72.8562,
        "elevation_m": 8.0,
        "catchment_area_sqm": 54000,
        "runoff_c": 0.84,
        "pipe_diameter_m": 1.2,
        "pipe_slope": 0.0035,
        "storage_area_sqm": 6000,
        "is_underpass": False,
        "notes": "Eastern elevated bypass. Safe from flooding even when Hindmata is underwater."
    },
    {
        "id": "tilak_bridge",
        "name": "Tilak Flyover (Dadar West-East Link)",
        "lat": 19.0182,
        "lon": 72.8385,
        "elevation_m": 9.5,
        "catchment_area_sqm": 35000,
        "runoff_c": 0.80,
        "pipe_diameter_m": 1.0,
        "pipe_slope": 0.005,
        "storage_area_sqm": 4000,
        "is_underpass": False,
        "notes": "Key overpass between East and West. Always dry, ideal emergency route."
    },
    {
        "id": "senapati_bapat_bypass",
        "name": "Senapati Bapat Marg Bypass",
        "lat": 19.0089,
        "lon": 72.8335,
        "elevation_m": 7.1,
        "catchment_area_sqm": 61000,
        "runoff_c": 0.85,
        "pipe_diameter_m": 1.3,
        "pipe_slope": 0.0028,
        "storage_area_sqm": 6200,
        "is_underpass": False,
        "notes": "Western arterial road running parallel to the central line; drains faster."
    },
    {
        "id": "matunga_station",
        "name": "Matunga Station Road",
        "lat": 19.0260,
        "lon": 72.8465,
        "elevation_m": 6.8,
        "catchment_area_sqm": 58000,
        "runoff_c": 0.83,
        "pipe_diameter_m": 1.2,
        "pipe_slope": 0.0022,
        "storage_area_sqm": 5500,
        "is_underpass": False,
        "notes": "Approach road towards north central suburbs."
    },
    {
        "id": "britannia_outfall",
        "name": "Britannia Outfall / Pumping Station",
        "lat": 19.0108,
        "lon": 72.8515,
        "elevation_m": 3.1,
        "catchment_area_sqm": 110000,
        "runoff_c": 0.91,
        "pipe_diameter_m": 2.2,
        "pipe_slope": 0.0010,
        "storage_area_sqm": 14000,
        "is_underpass": False,
        "notes": "Main stormwater pumping station discharging water into the sea."
    }
]

EDGES = [
    {
        "id": "e_kings_dadar",
        "from": "kings_circle",
        "to": "dadar_tt_circle",
        "distance_m": 1100,
        "speed_kmh": 35,
        "name": "Dr. Ambedkar Road",
        "is_flyover": False
    },
    {
        "id": "e_dadar_kings",
        "from": "dadar_tt_circle",
        "to": "kings_circle",
        "distance_m": 1100,
        "speed_kmh": 35,
        "name": "Dr. Ambedkar Road",
        "is_flyover": False
    },
    {
        "id": "e_dadar_hindmata",
        "from": "dadar_tt_circle",
        "to": "hindmata_junction",
        "distance_m": 620,
        "speed_kmh": 30,
        "name": "Dr. Ambedkar Road (Approach to Hindmata)",
        "is_flyover": False
    },
    {
        "id": "e_hindmata_dadar",
        "from": "hindmata_junction",
        "to": "dadar_tt_circle",
        "distance_m": 620,
        "speed_kmh": 30,
        "name": "Dr. Ambedkar Road",
        "is_flyover": False
    },
    {
        "id": "e_hindmata_parel",
        "from": "hindmata_junction",
        "to": "parel_tt",
        "distance_m": 850,
        "speed_kmh": 30,
        "name": "Dr. Ambedkar Road (Hindmata to Parel)",
        "is_flyover": False
    },
    {
        "id": "e_parel_hindmata",
        "from": "parel_tt",
        "to": "hindmata_junction",
        "distance_m": 850,
        "speed_kmh": 30,
        "name": "Dr. Ambedkar Road",
        "is_flyover": False
    },
    {
        "id": "e_parel_kem",
        "from": "parel_tt",
        "to": "kem_hospital_gate",
        "distance_m": 430,
        "speed_kmh": 25,
        "name": "Acharya Donde Marg (To KEM Hospital)",
        "is_flyover": False
    },
    {
        "id": "e_kem_parel",
        "from": "kem_hospital_gate",
        "to": "parel_tt",
        "distance_m": 430,
        "speed_kmh": 25,
        "name": "Acharya Donde Marg",
        "is_flyover": False
    },
    {
        "id": "e_dadar_tilak",
        "from": "dadar_tt_circle",
        "to": "tilak_bridge",
        "distance_m": 560,
        "speed_kmh": 35,
        "name": "Tilak Bridge Ramp",
        "is_flyover": True
    },
    {
        "id": "e_tilak_dadar",
        "from": "tilak_bridge",
        "to": "dadar_tt_circle",
        "distance_m": 560,
        "speed_kmh": 35,
        "name": "Tilak Bridge",
        "is_flyover": True
    },
    {
        "id": "e_tilak_senapati",
        "from": "tilak_bridge",
        "to": "senapati_bapat_bypass",
        "distance_m": 1180,
        "speed_kmh": 40,
        "name": "Senapati Bapat Marg Bypass",
        "is_flyover": True
    },
    {
        "id": "e_senapati_tilak",
        "from": "senapati_bapat_bypass",
        "to": "tilak_bridge",
        "distance_m": 1180,
        "speed_kmh": 40,
        "name": "Senapati Bapat Marg",
        "is_flyover": True
    },
    {
        "id": "e_senapati_parel",
        "from": "senapati_bapat_bypass",
        "to": "parel_tt",
        "distance_m": 720,
        "speed_kmh": 30,
        "name": "J.B. Marg Link to Parel",
        "is_flyover": False
    },
    {
        "id": "e_parel_senapati",
        "from": "parel_tt",
        "to": "senapati_bapat_bypass",
        "distance_m": 720,
        "speed_kmh": 30,
        "name": "J.B. Marg",
        "is_flyover": False
    },
    {
        "id": "e_dadar_wadala",
        "from": "dadar_tt_circle",
        "to": "wadala_bridge",
        "distance_m": 1250,
        "speed_kmh": 40,
        "name": "Tilak Road to Wadala Bridge",
        "is_flyover": True
    },
    {
        "id": "e_wadala_dadar",
        "from": "wadala_bridge",
        "to": "dadar_tt_circle",
        "distance_m": 1250,
        "speed_kmh": 40,
        "name": "Wadala Bridge to Dadar",
        "is_flyover": True
    },
    {
        "id": "e_wadala_britannia",
        "from": "wadala_bridge",
        "to": "britannia_outfall",
        "distance_m": 820,
        "speed_kmh": 35,
        "name": "R.A. Kidwai Road",
        "is_flyover": False
    },
    {
        "id": "e_britannia_wadala",
        "from": "britannia_outfall",
        "to": "wadala_bridge",
        "distance_m": 820,
        "speed_kmh": 35,
        "name": "R.A. Kidwai Road",
        "is_flyover": False
    },
    {
        "id": "e_britannia_kem",
        "from": "britannia_outfall",
        "to": "kem_hospital_gate",
        "distance_m": 1150,
        "speed_kmh": 35,
        "name": "Jerbai Wadia Road to KEM Gate",
        "is_flyover": True
    },
    {
        "id": "e_kem_britannia",
        "from": "kem_hospital_gate",
        "to": "britannia_outfall",
        "distance_m": 1150,
        "speed_kmh": 35,
        "name": "Jerbai Wadia Road",
        "is_flyover": True
    },
    {
        "id": "e_kings_matunga",
        "from": "kings_circle",
        "to": "matunga_station",
        "distance_m": 680,
        "speed_kmh": 30,
        "name": "Bhandarkar Road",
        "is_flyover": False
    },
    {
        "id": "e_matunga_kings",
        "from": "matunga_station",
        "to": "kings_circle",
        "distance_m": 680,
        "speed_kmh": 30,
        "name": "Bhandarkar Road",
        "is_flyover": False
    },
    {
        "id": "e_matunga_dadar",
        "from": "matunga_station",
        "to": "dadar_tt_circle",
        "distance_m": 790,
        "speed_kmh": 30,
        "name": "L.N. Road",
        "is_flyover": False
    },
    {
        "id": "e_dadar_matunga",
        "from": "dadar_tt_circle",
        "to": "matunga_station",
        "distance_m": 790,
        "speed_kmh": 30,
        "name": "L.N. Road",
        "is_flyover": False
    }
]

HOSPITALS_AND_SERVICES = [
    {
        "id": "kem_hospital",
        "name": "KEM Hospital & Trauma Center",
        "type": "hospital",
        "lat": 19.0028,
        "lon": 72.8429,
        "near_node": "kem_hospital_gate",
        "capacity": "1,800 Beds | Main Trauma Hub",
        "phone": "022-2410-7000",
        "status": "OPEN"
    },
    {
        "id": "tata_memorial",
        "name": "Tata Memorial Hospital",
        "type": "hospital",
        "lat": 19.0045,
        "lon": 72.8438,
        "near_node": "kem_hospital_gate",
        "capacity": "700 Cancer Care Beds",
        "phone": "022-2417-7000",
        "status": "OPEN"
    },
    {
        "id": "dadar_fire_station",
        "name": "Dadar Fire & Rescue Station (No. 14)",
        "type": "fire_station",
        "lat": 19.0175,
        "lon": 72.8448,
        "near_node": "dadar_tt_circle",
        "capacity": "6 Water Tenders, 2 Rescue Boats",
        "phone": "101 / 022-2414-2222",
        "status": "STANDBY"
    },
    {
        "id": "britannia_pump",
        "name": "Britannia Stormwater Pumping Station",
        "type": "pumping_station",
        "lat": 19.0112,
        "lon": 72.8520,
        "near_node": "britannia_outfall",
        "capacity": "6x 6,000 L/s Diesel Pumps",
        "phone": "022-2415-8890",
        "status": "OPERATIONAL"
    },
    {
        "id": "tilak_substation",
        "name": "BEST 33kV Power Substation",
        "type": "substation",
        "lat": 19.0152,
        "lon": 72.8412,
        "near_node": "hindmata_junction",
        "capacity": "Power grid for 45,000 homes & hospitals",
        "phone": "1912",
        "status": "NORMAL"
    },
    {
        "id": "khalsa_relief_camp",
        "name": "Khalsa College Flood Relief Shelter",
        "type": "shelter",
        "lat": 19.0250,
        "lon": 72.8570,
        "near_node": "wadala_bridge",
        "capacity": "Space for 1,500 people, drinking water & medical aid",
        "phone": "022-2401-2011",
        "status": "ACTIVE"
    }
]
