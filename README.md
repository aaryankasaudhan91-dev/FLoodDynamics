# FloodGuard — Urban Flood Nowcasting & Safe Navigation Engine

FloodGuard is an urban flood projection and emergency routing engine built for South-Central Mumbai (Dadar, Hindmata, and Parel). During intense monsoon events, low-lying street depressions submerge rapidly, cutting off critical ambulance access to hospitals like KEM and Wadia. FloodGuard integrates real-time hydrometric and meteorological telemetry with a hydraulic runoff solver and safe route planner to guide ambulances and rescue teams around flooded corridors.

---

## System Architecture & Phase 1 Ingestion

Phase 1 establishes automated ingestion pipelines across government and municipal data sources:

1. **Central Water Commission (CWC) & India-WRIS**:
   - Continuous water level monitoring at Mithi River (Kurla) and Mahim Creek stations.
   - Stage-discharge power law rating curve: $Q = C_r \times (h - h_0)^\beta$.
   - Upstream reservoir monitoring (Vihar Lake & Tulsi Lake) tracking inflow, outflow, and live storage percentage.
2. **India Meteorological Department (IMD)**:
   - Automated Weather Stations (AWS) / Automatic Rain Gauges (ARG).
   - Doppler Weather Radar (DWR) Marshall-Palmer transformation ($Z = a \cdot R^b$) across convective, stratiform, and cyclonic monsoon regimes.
   - Ground clutter screening using Doppler velocity ($V \approx 0\text{ m/s}$) and dual-pol correlation ($RhoHV < 0.85$).
   - IMD NOWCAST flash flood polygon alerts and quantitative 3-hour precipitation forecasts.
3. **ISRO / NRSC Bhuvan Spatial Services**:
   - Hydrological conditioning of CartoDEM elevation rasters: sink depression filling and stream burning ($Z - \Delta z$).
4. **Survey of India (SoI) CORS**:
   - Geodetic height calibration from ellipsoidal GNSS heights to orthometric levels using the Mumbai geoid undulation model ($N = -42.85\text{ m}$).
5. **ISRO MOSDAC Satellite Precipitation**:
   - INSAT-3DR/3DS Hydro-Estimator Method (HEM) precipitation extraction with nodata masking and 300 mm/hr physical capping.
6. **Municipal IoT & SCADA (BMC BRIMSTOWAD)**:
   - Real-time ultrasonic drain transducers along arterial culverts (water depth, freeboard clearance, flow velocity).
   - Major storm water pumping stations (Britannia, Lovegrove, Cleveland, Haji Ali).
7. **3-Stage Quality Control (QC)**:
   - **Stage 1**: Gross physical limits check ($0 \le R \le 350\text{ mm/hr}$, $0 \le h \le \text{HFL} + 4\text{ m}$).
   - **Stage 2**: Rate of rise spike threshold ($|dh/dt| \le 4.0\text{ m/hr}$) and stuck sensor detection.
   - **Stage 3**: Spatial Z-score anomaly check against neighboring stations ($Z \le 3.5$).
8. **High-Availability Fallback Hierarchy**:
   - Dynamic failover cascading: Tier 0 (IMD AWS) $\rightarrow$ Tier 1 (IMD Radar) $\rightarrow$ Tier 2 (ISRO MOSDAC Satellite) $\rightarrow$ Tier 3 (IMD WRF 3km Forecast) $\rightarrow$ Tier 4 (Climatological Persistence).

---

## Getting Started

### 1. Requirements
- Python 3.10+
- Modern Web Browser (Chrome, Firefox, Edge)

### 2. Installation
Install project dependencies:
```bash
pip install -r requirements.txt
```

### 3. Running the Server
Start the local FastAPI development server:
```bash
python main.py
```
Or with uvicorn directly:
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser and navigate to:
```
http://127.0.0.1:8000
```

---

## Core API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/cwc/telemetry` | GET | CWC river gauge stage, discharge rating curve, and flood thresholds |
| `/api/v1/cwc/reservoir` | GET | Upstream lake storage level, inflow, outflow, and capacity utilization |
| `/api/v1/imd/nowcast` | GET | Active IMD flash flood alert polygon and quantitative forecast |
| `/api/v1/imd/radar-transform` | POST | Marshall-Palmer reflectivity (dBZ) to rain rate (mm/hr) conversion |
| `/api/v1/imd/clutter-filter` | POST | Screens out false radar echoes using Doppler velocity and dual-pol RhoHV |
| `/api/v1/bhuvan/hydro-condition` | POST | Applies priority-flood sink filling and stream burning to elevation grids |
| `/api/v1/soi/cors-calibrate` | GET | Converts ellipsoidal GPS height to orthometric height using Mumbai geoid |
| `/api/v1/scada/brimstowad` | GET | BMC drain transducer depth, freeboard clearance, and pumping station state |
| `/api/v1/qc/validate` | POST | 3-stage sensor sanity filter (gross bounds, rate of rise, spatial Z-score) |
| `/api/v1/pipeline/status` | GET | Status of all data ingestion feeds and active fallback tier |
| `/api/v1/pipeline/fallback-tier` | POST | Dynamically triggers failover to backup meteorological tiers |
| `/api/simulate` | POST | Runs hydraulic simulation ($Q = CIA$ & Manning's equation) |
| `/api/route` | POST | Computes standard vs flood-safe Dijkstra route bypassing waterlogged roads |
