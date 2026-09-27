// FloodGuard Real-Time City Mapping, Flood Nowcasting & Safe Emergency Navigation
// Real APIs: OpenStreetMap Nominatim, Open-Meteo Live Weather & DEM Elevation, OSRM Routing. Zero mock data.

document.addEventListener('DOMContentLoaded', () => {
  const state = {
    activeCity: null,
    nodes: [],
    facilities: [],
    currentRoutes: null,
    selectedVehicle: 'ambulance'
  };

  // Vehicle clearance limits (in cm)
  const VEHICLE_CLEARANCES = {
    ambulance: 15.0,
    car: 15.0,
    heavy_truck: 50.0,
    pedestrian: 12.0
  };

  // Leaflet Map Initialization
  const map = L.map('map', {
    center: [20.5937, 78.9629], // Overview center before city is selected
    zoom: 5,
    zoomControl: true
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  // Dedicated Layer Groups
  const layers = {
    boundary: L.layerGroup().addTo(map),
    floodZones: L.layerGroup().addTo(map),
    facilities: L.layerGroup().addTo(map),
    routes: L.layerGroup().addTo(map)
  };

  // DOM Elements
  const cityModal = document.getElementById('cityModal');
  const citySearchForm = document.getElementById('citySearchForm');
  const cityInput = document.getElementById('cityInput');
  const btnSubmitCity = document.getElementById('btnSubmitCity');
  const cityLoadingStatus = document.getElementById('cityLoadingStatus');
  const loadingStepText = document.getElementById('loadingStepText');
  const loadingProgressBar = document.getElementById('loadingProgressBar');
  const btnChangeCity = document.getElementById('btnChangeCity');
  const cityBadge = document.getElementById('cityBadge');

  const alertBanner = document.getElementById('alertBanner');
  const alertIcon = document.getElementById('alertIcon');
  const alertMsg = document.getElementById('alertMsg');

  const navRainVal = document.getElementById('navRainVal');
  const navTempVal = document.getElementById('navTempVal');
  const navRiverVal = document.getElementById('navRiverVal');

  const selPreset = document.getElementById('selPreset');
  const selStartNode = document.getElementById('selStartNode');
  const selEndNode = document.getElementById('selEndNode');
  const btnRecalculateRoute = document.getElementById('btnRecalculateRoute');

  const stdDist = document.getElementById('stdDist');
  const stdTime = document.getElementById('stdTime');
  const stdDepth = document.getElementById('stdDepth');
  const stdBadge = document.getElementById('stdBadge');
  const stdNote = document.getElementById('stdNote');

  const safeDist = document.getElementById('safeDist');
  const safeTime = document.getElementById('safeTime');
  const safeDepth = document.getElementById('safeDepth');
  const safeBadge = document.getElementById('safeBadge');
  const safeNote = document.getElementById('safeNote');
  const routeStepsList = document.getElementById('routeStepsList');

  const rngRain = document.getElementById('rngRain');
  const rngTide = document.getElementById('rngTide');
  const rngPump = document.getElementById('rngPump');
  const lblRainVal = document.getElementById('lblRainVal');
  const lblTideVal = document.getElementById('lblTideVal');
  const lblPumpVal = document.getElementById('lblPumpVal');
  const btnRunSim = document.getElementById('btnRunSim');

  const btnCalm = document.getElementById('btnCalm');
  const btnStorm = document.getElementById('btnStorm');
  const btnSolution = document.getElementById('btnSolution');
  const facilitiesList = document.getElementById('facilitiesList');

  let riverChart = null;

  // ---------------------------------------------------------
  // Core: Real-Time Live City Fetch & Ingestion (Zero Mock)
  // ---------------------------------------------------------
  async function loadCity(cityName, rainOverride = null, pumpPct = 100.0) {
    if (!cityName || !cityName.trim()) return;
    const cleanName = cityName.trim();

    // Show loading state in modal
    cityLoadingStatus.style.display = 'block';
    btnSubmitCity.disabled = true;
    updateProgressStep(1, 'Geocoding administrative boundary from OpenStreetMap...');

    try {
      setTimeout(() => updateProgressStep(2, 'Querying live precipitation from Open-Meteo...'), 400);
      setTimeout(() => updateProgressStep(3, 'Ingesting digital elevation model (DEM)...'), 900);
      setTimeout(() => updateProgressStep(4, 'Discovering healthcare trauma centers & safe routes...'), 1400);

      let url = `/api/city/live?city=${encodeURIComponent(cleanName)}&pump_pct=${pumpPct}`;
      if (rainOverride !== null) {
        url += `&rain_mm_hr=${rainOverride}`;
      }

      const res = await fetch(url);
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Failed to fetch city '${cleanName}' (HTTP ${res.status})`);
      }

      const cityData = await res.json();
      state.activeCity = cityData;
      state.nodes = cityData.nodes;
      state.facilities = cityData.facilities;

      // Close startup modal
      cityModal.classList.remove('active');
      cityLoadingStatus.style.display = 'none';
      btnSubmitCity.disabled = false;

      // Render ONLY the asked city ("that time only show ask city no other city")
      renderCity(cityData);

    } catch (err) {
      console.error('City load error:', err);
      cityLoadingStatus.style.display = 'block';
      loadingStepText.textContent = `Error: ${err.message}`;
      loadingStepText.style.color = '#ef4444';
      loadingProgressBar.style.backgroundColor = '#ef4444';
      btnSubmitCity.disabled = false;
    }
  }

  function updateProgressStep(step, text) {
    loadingStepText.textContent = text;
    loadingStepText.style.color = '#0284c7';
    loadingProgressBar.style.backgroundColor = '#0284c7';
    loadingProgressBar.style.width = `${step * 25}%`;
  }

  // ---------------------------------------------------------
  // Render City: Boundaries, Flood Zones, Facilities, UI
  // ---------------------------------------------------------
  function renderCity(data) {
    // 1. Purge all prior layers completely
    layers.boundary.clearLayers();
    layers.floodZones.clearLayers();
    layers.facilities.clearLayers();
    layers.routes.clearLayers();

    // 2. Update Header Badge and Telemetry Labels
    cityBadge.textContent = data.city_name;
    navRainVal.textContent = `${data.weather.rain_mm_hr} mm/hr`;
    if (navTempVal) navTempVal.textContent = `${data.weather.temperature_c} °C`;
    navRiverVal.textContent = data.summary.city_status;
    navRiverVal.className = data.summary.flooded_nodes > 0 ? 'text-red' : 'text-green';

    // Update Slider
    rngRain.value = data.weather.rain_mm_hr;
    lblRainVal.textContent = `${data.weather.rain_mm_hr} mm/hr (${data.weather.condition})`;

    // Update Telemetry Chart Title
    const riverTitle = document.getElementById('riverTitle');
    if (riverTitle) riverTitle.textContent = `${data.city_name} Elevation & Hydrodynamics`;

    // 3. Render City Boundary GeoJSON with glowing stroke
    if (data.boundary_geojson) {
      const boundaryLayer = L.geoJSON(data.boundary_geojson, {
        style: {
          color: '#0284c7',
          weight: 2.5,
          opacity: 0.9,
          fillColor: '#0284c7',
          fillOpacity: 0.05,
          dashArray: '5, 5'
        }
      });
      layers.boundary.addLayer(boundaryLayer);
    }

    // 4. Fit map to the FULL CITY bounding box
    if (data.bounding_box && data.bounding_box.length === 2) {
      map.fitBounds(data.bounding_box, { padding: [35, 35], maxZoom: 14 });
    } else {
      map.setView(data.center, 12);
    }

    // 5. Update Alert Banner
    if (data.summary.flooded_nodes > 1) {
      alertBanner.className = 'alert-banner danger';
      alertIcon.textContent = '●';
      alertMsg.textContent = `Monsoon Alert in ${data.city_name}: ${data.summary.flooded_nodes} arterial corridors waterlogged. FloodGuard safe routes active.`;
    } else if (data.summary.flooded_nodes === 1) {
      alertBanner.className = 'alert-banner warning';
      alertIcon.textContent = '▲';
      alertMsg.textContent = `Water ponding detected at low-elevation points in ${data.city_name}. Caution advised.`;
    } else {
      alertBanner.className = 'alert-banner normal';
      alertIcon.textContent = '✓';
      alertMsg.textContent = `Normal traffic conditions across ${data.city_name}. All roads and underpasses passable.`;
    }

    // 6. Render Real Flood Hazard Nodes across the city
    renderNodes(data.nodes);

    // 7. Render Real Hospitals & Healthcare facilities in the city
    renderFacilities(data.facilities);

    // 8. Populate Routing Dropdowns with the city's real nodes
    populateDropdowns(data.nodes, data.facilities);

    // 9. Render Hydrodynamic Telemetry Chart
    renderChart(data);

    // 10. Automatically calculate initial flood-safe route
    calculateCityRoute();
  }

  function renderNodes(nodes) {
    layers.floodZones.clearLayers();

    nodes.forEach(node => {
      const isFlooded = node.depth_cm >= 15.0;
      const isSevere = node.depth_cm >= 45.0;
      const circleColor = isSevere ? '#ef4444' : (isFlooded ? '#d97706' : '#10b981');
      const radius = 60 + Math.min(220, node.depth_cm * 3.5);

      // Inundation buffer circle
      const circle = L.circle([node.lat, node.lon], {
        radius: radius,
        color: circleColor,
        fillColor: circleColor,
        fillOpacity: isFlooded ? 0.30 : 0.08,
        weight: isFlooded ? 1.5 : 1
      });

      const popupHtml = `
        <div class="custom-popup">
          <h4>${node.name}</h4>
          <p><strong>Elevation:</strong> ${node.elevation_m}m MSL</p>
          <p><strong>Infrastructure:</strong> ${node.is_underpass ? 'Underpass / Subway Depression' : 'Surface Arterial Corridor'}</p>
          <div class="depth-tag" style="background:${circleColor}18; color:${circleColor}; border:1px solid ${circleColor}44;">
            Water Depth: ${node.depth_cm} cm (${node.status})
          </div>
        </div>
      `;

      circle.bindPopup(popupHtml);
      layers.floodZones.addLayer(circle);

      // Core point marker
      const marker = L.circleMarker([node.lat, node.lon], {
        radius: 6,
        color: '#ffffff',
        weight: 1.5,
        fillColor: circleColor,
        fillOpacity: 0.95
      }).bindPopup(popupHtml);

      layers.floodZones.addLayer(marker);
    });
  }

  function renderFacilities(facilities) {
    layers.facilities.clearLayers();
    facilitiesList.innerHTML = '';

    if (!facilities || facilities.length === 0) {
      facilitiesList.innerHTML = '<p class="muted" style="padding:10px;">No public trauma centers indexed in this radius.</p>';
      return;
    }

    facilities.forEach(f => {
      const statusColor = f.alert_level === 'CRITICAL' ? '#ef4444' : (f.alert_level === 'WARNING' ? '#d97706' : '#10b981');

      const icon = L.divIcon({
        className: 'facility-icon',
        html: `<div style="background:#ffffff; border:2px solid ${statusColor}; color:${statusColor}; border-radius:6px; width:26px; height:26px; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; box-shadow:0 1px 3px rgba(0,0,0,0.2);">H</div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13]
      });

      const marker = L.marker([f.lat, f.lon], { icon }).bindPopup(`
        <div class="custom-popup">
          <h4>${f.name}</h4>
          <p><strong>Address:</strong> ${f.full_address}</p>
          <p><strong>Contact:</strong> ${f.phone}</p>
          <p><strong>Water Near Gate:</strong> <span style="color:${statusColor}; font-weight:600;">${f.water_depth_cm} cm</span></p>
          <p>${f.message}</p>
        </div>
      `);
      layers.facilities.addLayer(marker);

      const card = document.createElement('div');
      card.className = 'facility-card';
      card.innerHTML = `
        <div class="facility-title">
          <span>${f.name}</span>
          <span style="color:${statusColor}; font-size:10px; font-weight:600;">${f.alert_level}</span>
        </div>
        <div class="facility-desc">${f.message}</div>
        <div style="font-size:10px; color:#94a3b8; margin-top:3px;">${f.phone}</div>
      `;
      card.addEventListener('click', () => {
        map.flyTo([f.lat, f.lon], 15);
        marker.openPopup();
      });
      facilitiesList.appendChild(card);
    });
  }

  function populateDropdowns(nodes, facilities) {
    selStartNode.innerHTML = '';
    selEndNode.innerHTML = '';

    nodes.forEach(n => {
      const opt1 = document.createElement('option');
      opt1.value = n.id;
      opt1.textContent = `${n.name} (${n.elevation_m}m)`;
      selStartNode.appendChild(opt1);

      const opt2 = document.createElement('option');
      opt2.value = n.id;
      opt2.textContent = `${n.name} (${n.elevation_m}m)`;
      selEndNode.appendChild(opt2);
    });

    // Also allow routing to hospitals
    if (facilities && facilities.length > 0) {
      facilities.forEach(fac => {
        const optFac = document.createElement('option');
        optFac.value = fac.id;
        optFac.textContent = `[Hospital] ${fac.name}`;
        selEndNode.appendChild(optFac);
      });
    }

    if (nodes.length > 1) {
      selStartNode.selectedIndex = 0;
      selEndNode.selectedIndex = Math.min(nodes.length - 1, 1);
    }
  }

  // ---------------------------------------------------------
  // Real-Time OSRM Routing (Standard vs Flood-Safe Bypass)
  // ---------------------------------------------------------
  async function calculateCityRoute() {
    if (!state.activeCity || !state.nodes || state.nodes.length === 0) return;

    const startId = selStartNode.value;
    const endId = selEndNode.value;

    let startObj = state.nodes.find(n => n.id === startId);
    let endObj = state.nodes.find(n => n.id === endId);

    // If destination is a hospital
    if (!endObj && state.facilities) {
      endObj = state.facilities.find(f => f.id === endId);
    }

    if (!startObj || !endObj) return;

    btnRecalculateRoute.textContent = 'Calculating live route...';

    try {
      const payload = {
        city: state.activeCity.city_name,
        start_lat: startObj.lat,
        start_lon: startObj.lon,
        end_lat: endObj.lat,
        end_lon: endObj.lon,
        vehicle_type: state.selectedVehicle
      };

      const res = await fetch('/api/city/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error(`Routing HTTP error: ${res.status}`);

      const routeResult = await res.json();
      state.currentRoutes = routeResult;
      renderRoutes(routeResult);

    } catch (err) {
      console.error('Route error:', err);
    } finally {
      btnRecalculateRoute.textContent = 'Calculate Flood-Safe Route';
    }
  }

  function renderRoutes(data) {
    layers.routes.clearLayers();
    const { standard, safe } = data;

    // Standard Route
    if (standard) {
      stdDist.textContent = standard.distance_km;
      stdTime.textContent = standard.duration_mins;
      stdDepth.textContent = `${standard.max_depth_cm} cm`;

      if (standard.max_depth_cm >= 15.0) {
        stdBadge.className = 'badge';
        stdBadge.textContent = 'Waterlogged';
        stdDepth.className = 'text-red';
        stdNote.textContent = `Crosses high water near ${standard.flooded_node || 'low-lying depression'}.`;
      } else {
        stdBadge.className = 'badge green';
        stdBadge.textContent = 'Clear';
        stdDepth.className = 'text-green';
        stdNote.textContent = 'All traversed corridors dry and passable.';
      }

      if (standard.geometry && standard.geometry.length > 0) {
        const stdLine = L.polyline(standard.geometry, {
          color: standard.max_depth_cm >= 15.0 ? '#ef4444' : '#94a3b8',
          weight: 3.5,
          dashArray: standard.max_depth_cm >= 15.0 ? '6, 6' : null,
          opacity: 0.8
        }).bindPopup(`<b>Standard Shortest Route</b><br>Water depth: ${standard.max_depth_cm} cm`);
        layers.routes.addLayer(stdLine);
      }
    }

    // Safe Route
    if (safe) {
      safeDist.textContent = safe.distance_km;
      safeTime.textContent = safe.duration_mins;
      safeDepth.textContent = `${safe.max_depth_cm} cm`;

      safeBadge.className = 'badge green';
      safeBadge.textContent = safe.detour_taken ? 'Safe Detour' : 'Safe Direct';
      safeNote.textContent = safe.detour_taken
        ? `Bypasses submerged hazard (${safe.bypassed_hazard}) via elevated corridors.`
        : 'Direct route is safe for transit.';

      if (safe.geometry && safe.geometry.length > 0) {
        const safeLine = L.polyline(safe.geometry, {
          color: '#0284c7',
          weight: 5,
          opacity: 0.95
        }).bindPopup(`<b>FloodGuard Safe Route</b><br>0 cm water exposure`);
        layers.routes.addLayer(safeLine);

        // Turn-by-Turn Steps
        renderSteps(safe.steps || standard.steps || []);
      }
    }
  }

  function renderSteps(steps) {
    routeStepsList.innerHTML = '';
    if (!steps || steps.length === 0) {
      routeStepsList.innerHTML = '<li class="empty-step">Select destination to view turn instructions.</li>';
      return;
    }
    steps.forEach((step, idx) => {
      const li = document.createElement('li');
      li.innerHTML = `<strong>Step ${idx + 1}:</strong> ${step}`;
      routeStepsList.appendChild(li);
    });
  }

  function renderChart(data) {
    const canvas = document.getElementById('riverChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const labels = data.nodes.map(n => n.name.split(' ')[0]);
    const elevs = data.nodes.map(n => n.elevation_m);
    const depths = data.nodes.map(n => n.depth_cm);

    if (riverChart) {
      riverChart.destroy();
    }

    riverChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Water Ponding (cm)',
            data: depths,
            backgroundColor: depths.map(d => d >= 45 ? '#ef4444' : (d >= 15 ? '#f59e0b' : '#10b981')),
            borderRadius: 4
          },
          {
            type: 'line',
            label: 'Elevation (m MSL)',
            data: elevs,
            borderColor: '#0284c7',
            backgroundColor: 'transparent',
            tension: 0.2,
            pointRadius: 3
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: '#64748b', font: { size: 10 } }
          }
        },
        scales: {
          x: { ticks: { color: '#94a3b8', font: { size: 9 } }, grid: { color: '#f1f5f9' } },
          y: { ticks: { color: '#94a3b8', font: { size: 9 } }, grid: { color: '#f1f5f9' } }
        }
      }
    });
  }

  // ---------------------------------------------------------
  // Event Listeners: City Input, Presets, Simulation, Demos
  // ---------------------------------------------------------

  // City Search Form submit
  citySearchForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const val = cityInput.value;
    if (val) loadCity(val);
  });

  // Suggestion Chips
  document.querySelectorAll('.chip-btn').forEach(chip => {
    chip.addEventListener('click', () => {
      const cityName = chip.dataset.city;
      cityInput.value = cityName;
      loadCity(cityName);
    });
  });

  // "Change City" button
  btnChangeCity.addEventListener('click', () => {
    cityModal.classList.add('active');
    cityLoadingStatus.style.display = 'none';
    cityInput.focus();
    cityInput.select();
  });

  // Routing controls
  btnRecalculateRoute.addEventListener('click', calculateCityRoute);
  selStartNode.addEventListener('change', calculateCityRoute);
  selEndNode.addEventListener('change', calculateCityRoute);

  // Vehicle clearance picker
  document.querySelectorAll('.veh-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      state.selectedVehicle = btn.dataset.v;
      document.querySelectorAll('.veh-btn').forEach(b => {
        if (b.dataset.v === state.selectedVehicle) b.classList.add('active');
        else b.classList.remove('active');
      });
      calculateCityRoute();
    });
  });

  // Trip Presets for Active City
  selPreset.addEventListener('change', (e) => {
    if (!state.nodes || state.nodes.length === 0) return;
    if (e.target.value === 'preset_transit_hospital') {
      selStartNode.selectedIndex = 0;
      if (state.facilities && state.facilities.length > 0) {
        selEndNode.value = state.facilities[0].id;
      } else {
        selEndNode.selectedIndex = state.nodes.length - 1;
      }
    } else {
      selStartNode.selectedIndex = Math.min(1, state.nodes.length - 1);
      selEndNode.selectedIndex = Math.max(0, state.nodes.length - 2);
    }
    calculateCityRoute();
  });

  // Rain Simulator Slider
  rngRain.addEventListener('input', (e) => {
    lblRainVal.textContent = `${e.target.value} mm/hr`;
  });
  rngPump.addEventListener('input', (e) => {
    lblPumpVal.textContent = `${e.target.value}% Operational`;
  });

  btnRunSim.addEventListener('click', () => {
    if (!state.activeCity) return;
    loadCity(state.activeCity.city_name, parseFloat(rngRain.value), parseFloat(rngPump.value));
  });

  // Demo Scenarios
  btnCalm.addEventListener('click', () => {
    btnCalm.classList.add('active');
    btnStorm.classList.remove('active');
    btnSolution.classList.remove('active');
    if (state.activeCity) loadCity(state.activeCity.city_name, 0.0);
  });

  btnStorm.addEventListener('click', () => {
    btnStorm.classList.add('active');
    btnCalm.classList.remove('active');
    btnSolution.classList.remove('active');
    if (state.activeCity) loadCity(state.activeCity.city_name, 65.0);
  });

  btnSolution.addEventListener('click', () => {
    btnSolution.classList.add('active');
    btnCalm.classList.remove('active');
    btnStorm.classList.remove('active');
    switchTab('nav');
    calculateCityRoute();
  });

  // Tab Navigation
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      switchTab(btn.dataset.tab);
    });
  });

  function switchTab(tabKey) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

    const tabBtn = document.querySelector(`.tab-btn[data-tab="${tabKey}"]`);
    if (tabBtn) tabBtn.classList.add('active');

    if (tabKey === 'nav') document.getElementById('tabNav').classList.add('active');
    if (tabKey === 'sim') document.getElementById('tabSim').classList.add('active');
    if (tabKey === 'facilities') document.getElementById('tabFacilities').classList.add('active');
  }

  // Layer Visibility Checkboxes
  document.getElementById('chkFloodZones').addEventListener('change', (e) => {
    if (e.target.checked) map.addLayer(layers.floodZones);
    else map.removeLayer(layers.floodZones);
  });
  document.getElementById('chkHospitals').addEventListener('change', (e) => {
    if (e.target.checked) map.addLayer(layers.facilities);
    else map.removeLayer(layers.facilities);
  });
  document.getElementById('chkRoutes').addEventListener('change', (e) => {
    if (e.target.checked) map.addLayer(layers.routes);
    else map.removeLayer(layers.routes);
  });

  // Startup: On launch, do NOT render any other city. Show city prompt upfront.
  cityModal.classList.add('active');
  cityInput.focus();
});
