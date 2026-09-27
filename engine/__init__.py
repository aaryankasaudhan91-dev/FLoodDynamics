"""Engine package initialization providing unified access to the 4 domain modules:
- spatial_data: Nodes, edges, infrastructure coordinates, and SQL schema
- telemetry: Multi-source Indian agency telemetry ingestors and QC engines
- hydrodynamics: Coupled 1D-2D hydrodynamic engine and hydraulic solver
- navigation: Dynamic hydrodynamic routing, NavIC positioning, and evacuation engines
"""

import sys
from . import spatial_data
from . import telemetry
from . import hydrodynamics
from . import navigation

# Re-export core classes and objects for top-level access
from .spatial_data import (
    NODES,
    EDGES,
    HOSPITALS_AND_SERVICES,
    DB_SCHEMA_SQL,
)
from .telemetry import (
    CWCIndiaWRISEngine,
    IMDWeatherEngine,
    ISROBhuvanSpatialEngine,
    SurveyOfIndiaCORSEngine,
    ISROMOSDACPrecipEngine,
    MunicipalSCADAEngine,
    MultiStageQCEngine,
    FallbackHierarchyEngine,
)
from .hydrodynamics import (
    PreissmannSlotPipe,
    Coupled1D2DExchange,
    DynamicRoughnessBlockage,
    EstuarineTidalBoundary,
    HydrographSignalAnalyzer,
    HydraulicModel,
    phase2_router,
)
from .navigation import (
    VehicleClass,
    VehicleLimits,
    VEHICLE_THRESHOLDS,
    calculate_hydrodynamic_forces,
    calculate_edge_cost,
    NavICEngine,
    SMSFallbackProtocol,
    SmartNavigationRouter,
    EvacuationShelterEngine,
    FloodRouter,
    VEHICLES,
    phase4_router,
)

# Compatibility aliases for legacy module references
sys.modules[f"{__name__}.neighborhood_data"] = spatial_data
sys.modules[f"{__name__}.phase1_ingestion"] = telemetry
sys.modules[f"{__name__}.hydraulic_model"] = hydrodynamics
sys.modules[f"{__name__}.phase2_hydrodynamics"] = hydrodynamics
sys.modules[f"{__name__}.phase2_routes"] = hydrodynamics
sys.modules[f"{__name__}.routing_engine"] = navigation
sys.modules[f"{__name__}.phase4_navigation"] = navigation
sys.modules[f"{__name__}.phase4_routes"] = navigation

__all__ = [
    "spatial_data",
    "telemetry",
    "hydrodynamics",
    "navigation",
    "NODES",
    "EDGES",
    "HOSPITALS_AND_SERVICES",
    "DB_SCHEMA_SQL",
    "CWCIndiaWRISEngine",
    "IMDWeatherEngine",
    "ISROBhuvanSpatialEngine",
    "SurveyOfIndiaCORSEngine",
    "ISROMOSDACPrecipEngine",
    "MunicipalSCADAEngine",
    "MultiStageQCEngine",
    "FallbackHierarchyEngine",
    "PreissmannSlotPipe",
    "Coupled1D2DExchange",
    "DynamicRoughnessBlockage",
    "EstuarineTidalBoundary",
    "HydrographSignalAnalyzer",
    "HydraulicModel",
    "phase2_router",
    "VehicleClass",
    "VehicleLimits",
    "VEHICLE_THRESHOLDS",
    "calculate_hydrodynamic_forces",
    "calculate_edge_cost",
    "NavICEngine",
    "SMSFallbackProtocol",
    "SmartNavigationRouter",
    "EvacuationShelterEngine",
    "FloodRouter",
    "VEHICLES",
    "phase4_router",
]
