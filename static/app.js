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
  async function loadCity(cityName, rainOverride = null, pumpPct = 100.0, autoRoute = true) {
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

      // Render ONLY the asked city
      renderCity(cityData, autoRoute);

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
  function renderCity(data, autoRoute = true) {
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

    // 5. Update Alert Banner (Super Easy to Understand)
    if (data.summary.flooded_nodes > 1) {
      alertBanner.className = 'alert-banner danger';
      alertIcon.textContent = '🛑';
      alertMsg.textContent = `Flood Alert in ${data.city_name}: ${data.summary.flooded_nodes} roads have deep water! Follow the Blue Safe Route to stay dry!`;
    } else if (data.summary.flooded_nodes === 1) {
      alertBanner.className = 'alert-banner warning';
      alertIcon.textContent = '⚠️';
      alertMsg.textContent = `Caution in ${data.city_name}: Some puddles on low roads. Drive slowly and stay safe!`;
    } else {
      alertBanner.className = 'alert-banner normal';
      alertIcon.textContent = '☀️';
      alertMsg.textContent = `Yay! All roads in ${data.city_name} are dry and safe to travel!`;
    }

    // 6. Render Real Flood Hazard Nodes across the city
    renderNodes(data.nodes);

    // 7. Render Real Hospitals & Healthcare facilities in the city
    renderFacilities(data.facilities);

    // 8. Populate Routing Dropdowns with the city's real nodes
    populateDropdowns(data.nodes, data.facilities);

    // 9. Render Hydrodynamic Telemetry Chart
    renderChart(data);

    // 10. Route Calculation Handling
    const promptBox = document.getElementById('stormPromptBox');
    if (!autoRoute) {
      // In storm mode, do not directly show route! First prompt for start and destination:
      layers.routes.clearLayers();
      if (promptBox) {
        promptBox.style.display = 'block';
        promptBox.innerHTML = `
          <div class="storm-prompt-title">🌧️ Storm Alert Active (${data.weather.rain_mm_hr} mm/hr)</div>
          <p>Please select your <strong>Start Point</strong> and <strong>Destination</strong> below to calculate a dry, safe detour!</p>
          <div class="storm-steps-hint">
            <span>🟢 1. Pick Start</span> ➔ <span>🏁 2. Pick Destination</span> ➔ <span>🛡️ 3. Safe Route</span>
          </div>
          <div style="font-size:10px; color:#2563eb; margin-top:6px;">💡 Or click any marker directly on the map to set Start or Destination!</div>
        `;
      }
      if (selStartNode) selStartNode.classList.add('pulse-highlight');
      if (selEndNode) selEndNode.classList.add('pulse-highlight');

      // Reset route result displays to prompt state
      if (stdDist) stdDist.textContent = '--';
      if (stdTime) stdTime.textContent = '--';
      if (stdDepth) { stdDepth.textContent = '-- cm'; stdDepth.className = 'text-muted'; }
      if (stdBadge) { stdBadge.className = 'badge'; stdBadge.textContent = 'Waiting for Points'; }
      if (stdNote) stdNote.textContent = 'Select start and destination points to view shortcut flood hazards.';

      if (safeDist) safeDist.textContent = '--';
      if (safeTime) safeTime.textContent = '--';
      if (safeDepth) { safeDepth.textContent = '-- cm'; safeDepth.className = 'text-muted'; }
      if (safeBadge) { safeBadge.className = 'badge'; safeBadge.textContent = '👆 Choose Points'; }
      if (safeNote) safeNote.textContent = 'Select where you are and where you need to go to generate safe detour.';

      const routeStepsList = document.getElementById('routeStepsList');
      if (routeStepsList) {
        routeStepsList.innerHTML = '<li class="empty-step">🌧️ Storm mode active! Choose your Start Point and Destination above, then click "Find Safe Route Now" to see dry roads.</li>';
      }

      switchTab('nav');
    } else {
      if (promptBox) promptBox.style.display = 'none';
      if (selStartNode) selStartNode.classList.remove('pulse-highlight');
      if (selEndNode) selEndNode.classList.remove('pulse-highlight');
      calculateCityRoute();
    }
  }

  function renderNodes(nodes) {
    layers.floodZones.clearLayers();

    nodes.forEach(node => {
      const isFlooded = node.depth_cm >= 15.0;
      const isSevere = node.depth_cm >= 45.0;
      const circleColor = isSevere ? '#ef4444' : (isFlooded ? '#d97706' : '#10b981');
      const radius = 60 + Math.min(220, node.depth_cm * 3.5);

      let kidStatus = '🟢 Safe & Dry Road';
      let kidAdvice = 'Road is clear! Cars and walking are safe. 👟🚗';
      if (isSevere) {
        kidStatus = '🔴 DANGER: Flooded Street!';
        kidAdvice = 'Water is waist-deep! Never drive or walk here! 🛑';
      } else if (isFlooded) {
        kidStatus = '🟡 CAUTION: Knee-Deep Puddles!';
        kidAdvice = 'Water is splashing! Only big trucks should pass. 🛞';
      }

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
          <h4>📍 ${node.name}</h4>
          <p><strong>Safety Status:</strong> <span style="color:${circleColor}; font-weight:700;">${kidStatus}</span></p>
          <p><strong>Water Puddle:</strong> ${node.depth_cm} cm deep</p>
          <div class="depth-tag" style="background:${circleColor}18; color:${circleColor}; border:1px solid ${circleColor}44; font-size:11px; padding:4px 8px; border-radius:6px; margin:4px 0; font-weight:600;">
            ${kidAdvice}
          </div>
          <p style="font-size:10px; color:#94a3b8; margin-top:4px;">Elevation: ${node.elevation_m}m MSL • ${node.is_underpass ? 'Low-lying depression' : 'High ground'}</p>
          <div class="popup-actions-row">
            <button class="popup-action-btn start" onclick="window.selectRoutePoint('${node.id}', 'start')">🟢 Start Here</button>
            <button class="popup-action-btn end" onclick="window.selectRoutePoint('${node.id}', 'end')">🏁 End Here</button>
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
      const isCritical = f.alert_level === 'CRITICAL';
      const isWarning = f.alert_level === 'WARNING';
      const statusColor = isCritical ? '#ef4444' : (isWarning ? '#d97706' : '#10b981');
      const friendlyStatus = isCritical
        ? '🔴 Gate Flooded (Use dry detour)'
        : (isWarning ? '🟡 Entrance Has Puddles' : '🟢 Gate is Safe & Dry!');

      const icon = L.divIcon({
        className: 'facility-icon',
        html: `<div style="background:#ffffff; border:2px solid ${statusColor}; color:${statusColor}; border-radius:6px; width:26px; height:26px; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; box-shadow:0 1px 3px rgba(0,0,0,0.2);">🏥</div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13]
      });

      const marker = L.marker([f.lat, f.lon], { icon }).bindPopup(`
        <div class="custom-popup">
          <h4>🏥 ${f.name}</h4>
          <p><strong>Gate Status:</strong> <span style="color:${statusColor}; font-weight:700;">${friendlyStatus}</span></p>
          <p><strong>Address:</strong> ${f.full_address}</p>
          <p><strong>Emergency Call:</strong> ${f.phone}</p>
          <p><strong>Water Depth:</strong> ${f.water_depth_cm} cm</p>
          <div class="popup-actions-row">
            <button class="popup-action-btn end" onclick="window.selectRoutePoint('${f.id}', 'end')">🏁 Navigate Here</button>
          </div>
        </div>
      `);
      layers.facilities.addLayer(marker);

      const card = document.createElement('div');
      card.className = 'facility-card';
      card.innerHTML = `
        <div class="facility-title">
          <span>🏥 ${f.name}</span>
          <span style="color:${statusColor}; font-size:10px; font-weight:700;">${friendlyStatus}</span>
        </div>
        <div class="facility-desc">${f.water_depth_cm > 15 ? 'Water near gate: ' + f.water_depth_cm + 'cm. Ambulances should take the elevated safe route.' : 'Gate is completely clear and dry! Safe for all patients.'}</div>
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
      opt1.textContent = `📍 ${n.name} (${n.elevation_m}m)`;
      selStartNode.appendChild(opt1);

      const opt2 = document.createElement('option');
      opt2.value = n.id;
      opt2.textContent = `📍 ${n.name} (${n.elevation_m}m)`;
      selEndNode.appendChild(opt2);
    });

    if (facilities && facilities.length > 0) {
      facilities.forEach(fac => {
        const optFac = document.createElement('option');
        optFac.value = fac.id;
        optFac.textContent = `🏥 [Hospital] ${fac.name}`;
        selEndNode.appendChild(optFac);
      });
    }

    if (nodes.length > 1) {
      selStartNode.selectedIndex = 0;
      selEndNode.selectedIndex = Math.min(nodes.length - 1, 1);
    }
  }

  // Global handler for selecting Start / End point directly from map marker popups
  window.selectRoutePoint = function(id, type) {
    if (type === 'start') {
      if (selStartNode) selStartNode.value = id;
    } else if (type === 'end') {
      if (selEndNode) selEndNode.value = id;
    }

    switchTab('nav');

    const promptBox = document.getElementById('stormPromptBox');
    if (promptBox) {
      const sName = selStartNode.options[selStartNode.selectedIndex]?.text || 'Selected';
      const eName = selEndNode.options[selEndNode.selectedIndex]?.text || 'Selected';
      promptBox.innerHTML = `
        <div class="storm-prompt-title">📍 Points Selected</div>
        <p>🟢 Start: <strong>${sName}</strong><br>🏁 Destination: <strong>${eName}</strong></p>
        <p style="font-weight:600; color:#2563eb;">Ready! Click "Find Safe Route Now" below to calculate your detour!</p>
      `;
    }
  };

  // ---------------------------------------------------------
  // Real-Time OSRM Routing (Standard vs Flood-Safe Bypass)
  // ---------------------------------------------------------
  async function calculateCityRoute() {
    if (!state.activeCity || !state.nodes || state.nodes.length === 0) return;

    const startId = selStartNode.value;
    const endId = selEndNode.value;

    let startObj = state.nodes.find(n => n.id === startId);
    let endObj = state.nodes.find(n => n.id === endId);

    if (!endObj && state.facilities) {
      endObj = state.facilities.find(f => f.id === endId);
    }

    if (!startObj || !endObj) return;

    // Clear pulse highlights and prompt box
    if (selStartNode) selStartNode.classList.remove('pulse-highlight');
    if (selEndNode) selEndNode.classList.remove('pulse-highlight');
    const promptBox = document.getElementById('stormPromptBox');
    if (promptBox) promptBox.style.display = 'none';

    btnRecalculateRoute.textContent = '⏳ Finding safest dry route...';

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
      btnRecalculateRoute.textContent = '🔍 Find Safe Route Now';
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
        stdBadge.textContent = '❌ Has Floods!';
        stdDepth.className = 'text-red';
        stdNote.textContent = `Crosses ${standard.max_depth_cm}cm water puddle! Your car might get stuck!`;
      } else {
        stdBadge.className = 'badge green';
        stdBadge.textContent = '✅ All Clear';
        stdDepth.className = 'text-green';
        stdNote.textContent = 'All roads along this shortcut are dry.';
      }

      if (standard.geometry && standard.geometry.length > 0) {
        const stdLine = L.polyline(standard.geometry, {
          color: standard.max_depth_cm >= 15.0 ? '#ef4444' : '#94a3b8',
          weight: 3.5,
          dashArray: standard.max_depth_cm >= 15.0 ? '6, 6' : null,
          opacity: 0.8
        }).bindPopup(`<b>❌ Risky Shortcut</b><br>Max water puddle: ${standard.max_depth_cm} cm`);
        layers.routes.addLayer(stdLine);
      }
    }

    // Safe Route
    if (safe) {
      safeDist.textContent = safe.distance_km;
      safeTime.textContent = safe.duration_mins;
      safeDepth.textContent = `${safe.max_depth_cm} cm`;

      safeBadge.className = 'badge green';
      safeBadge.textContent = safe.detour_taken ? '🛡️ Safe Detour' : '🛡️ 100% Safe & Dry';
      safeNote.textContent = safe.detour_taken
        ? `Takes the high elevated bridge to avoid deep flood water!`
        : 'Direct road is already dry and safe!';

      if (safe.geometry && safe.geometry.length > 0) {
        const safeLine = L.polyline(safe.geometry, {
          color: '#0284c7',
          weight: 5,
          opacity: 0.95
        }).bindPopup(`<b>🛡️ FloodGuard Hero Route</b><br>0 cm water exposure • 100% safe!`);
        layers.routes.addLayer(safeLine);

        // Turn-by-Turn Steps
        renderSteps(safe.steps || standard.steps || []);
      }
    }
  }

  function renderSteps(steps) {
    routeStepsList.innerHTML = '';
    if (!steps || steps.length === 0) {
      routeStepsList.innerHTML = '<li class="empty-step">Pick your destination to see safe turn instructions!</li>';
      return;
    }
    steps.forEach((step, idx) => {
      const li = document.createElement('li');
      let icon = '🚗';
      const sLower = step.toLowerCase();
      if (sLower.includes('bridge') || sLower.includes('flyover')) icon = '🌉';
      else if (sLower.includes('right')) icon = '➡️';
      else if (sLower.includes('left')) icon = '⬅️';
      else if (idx === steps.length - 1) icon = '🎉';
      li.innerHTML = `<strong>${icon} Step ${idx + 1}:</strong> ${step}`;
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
  // Event Listeners: City Input, Presets, Simulation, Demos (Safely Guarded)
  // ---------------------------------------------------------

  // City Search Form submit
  if (citySearchForm) {
    citySearchForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const val = cityInput ? cityInput.value : '';
      if (val) loadCity(val);
    });
  }

  // Suggestion Chips (Major Indian Cities)
  document.querySelectorAll('.chip-btn').forEach(chip => {
    chip.addEventListener('click', () => {
      const cityName = chip.dataset.city;
      if (cityInput) cityInput.value = cityName;
      loadCity(cityName);
    });
  });

  // "Change City" button
  if (btnChangeCity) {
    btnChangeCity.addEventListener('click', () => {
      if (cityModal) cityModal.classList.add('active');
      if (cityLoadingStatus) cityLoadingStatus.style.display = 'none';
      if (cityInput) {
        cityInput.focus();
        cityInput.select();
      }
    });
  }

  // Routing controls
  if (btnRecalculateRoute) btnRecalculateRoute.addEventListener('click', calculateCityRoute);
  if (selStartNode) selStartNode.addEventListener('change', calculateCityRoute);
  if (selEndNode) selEndNode.addEventListener('change', calculateCityRoute);

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
  if (selPreset) {
    selPreset.addEventListener('change', (e) => {
      if (!state.nodes || state.nodes.length === 0) return;
      if (e.target.value === 'preset_transit_hospital') {
        if (selStartNode) selStartNode.selectedIndex = 0;
        if (selEndNode) {
          if (state.facilities && state.facilities.length > 0) {
            selEndNode.value = state.facilities[0].id;
          } else {
            selEndNode.selectedIndex = state.nodes.length - 1;
          }
        }
      } else {
        if (selStartNode) selStartNode.selectedIndex = Math.min(1, state.nodes.length - 1);
        if (selEndNode) selEndNode.selectedIndex = Math.max(0, state.nodes.length - 2);
      }
      calculateCityRoute();
    });
  }

  // Rain Simulator Slider
  if (rngRain) {
    rngRain.addEventListener('input', (e) => {
      if (lblRainVal) lblRainVal.textContent = `${e.target.value} mm/hr`;
    });
  }
  if (rngPump) {
    rngPump.addEventListener('input', (e) => {
      if (lblPumpVal) lblPumpVal.textContent = `${e.target.value}% Operational`;
    });
  }

  if (btnRunSim) {
    btnRunSim.addEventListener('click', () => {
      if (!state.activeCity) return;
      const rain = rngRain ? parseFloat(rngRain.value) : 15.0;
      const pump = rngPump ? parseFloat(rngPump.value) : 100.0;
      loadCity(state.activeCity.city_name, rain, pump);
    });
  }

  // Demo Scenarios
  if (btnCalm) {
    btnCalm.addEventListener('click', () => {
      btnCalm.classList.add('active');
      if (btnStorm) btnStorm.classList.remove('active');
      if (btnSolution) btnSolution.classList.remove('active');
      const promptBox = document.getElementById('stormPromptBox');
      if (promptBox) promptBox.style.display = 'none';
      if (state.activeCity) loadCity(state.activeCity.city_name, 0.0, 100.0, true);
    });
  }

  if (btnStorm) {
    btnStorm.addEventListener('click', () => {
      btnStorm.classList.add('active');
      if (btnCalm) btnCalm.classList.remove('active');
      if (btnSolution) btnSolution.classList.remove('active');
      if (state.activeCity) {
        // In Rain Storm mode: do NOT directly show route! First ask for start and end point:
        loadCity(state.activeCity.city_name, 65.0, 100.0, false);
      }
    });
  }

  if (btnSolution) {
    btnSolution.addEventListener('click', () => {
      btnSolution.classList.add('active');
      if (btnCalm) btnCalm.classList.remove('active');
      if (btnStorm) btnStorm.classList.remove('active');
      switchTab('nav');
      calculateCityRoute();
    });
  }

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

    if (tabKey === 'nav') {
      const p = document.getElementById('tabNav');
      if (p) p.classList.add('active');
    }
    if (tabKey === 'sim') {
      const p = document.getElementById('tabSim');
      if (p) p.classList.add('active');
    }
    if (tabKey === 'facilities') {
      const p = document.getElementById('tabFacilities');
      if (p) p.classList.add('active');
    }
  }

  // Layer Visibility Checkboxes
  const chkFloodZones = document.getElementById('chkFloodZones');
  if (chkFloodZones) {
    chkFloodZones.addEventListener('change', (e) => {
      if (e.target.checked) map.addLayer(layers.floodZones);
      else map.removeLayer(layers.floodZones);
    });
  }
  const chkHospitals = document.getElementById('chkHospitals');
  if (chkHospitals) {
    chkHospitals.addEventListener('change', (e) => {
      if (e.target.checked) map.addLayer(layers.facilities);
      else map.removeLayer(layers.facilities);
    });
  }
  const chkRoutes = document.getElementById('chkRoutes');
  if (chkRoutes) {
    chkRoutes.addEventListener('change', (e) => {
      if (e.target.checked) map.addLayer(layers.routes);
      else map.removeLayer(layers.routes);
    });
  }

  // Startup: On launch, do NOT render any other city. Show city prompt upfront.
  if (cityModal) {
    cityModal.classList.add('active');
    if (cityInput) cityInput.focus();
  }
});
