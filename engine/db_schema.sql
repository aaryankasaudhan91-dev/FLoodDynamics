-- FloodGuard TimescaleDB & PostGIS table definitions

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
