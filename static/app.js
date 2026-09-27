// FloodGuard interactive dashboard for Dadar-Hindmata emergency navigation and Phase 1 telemetry feeds.

document.addEventListener('DOMContentLoaded', () => {
  const state = {
    nodes: [],
    facilities: [],
    currentSim: null,
    currentRoutes: null,
    selectedVehicle: 'ambulance'
  };

  // Standard OpenStreetMap Tiles (100% Free, Zero API Key Watermark)
  const map = L.map('map', {
    center: [19.0145, 72.8430],
    zoom: 14,
    zoomControl: true
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  // Layer groups
  const layers = {
    floodZones: L.layerGroup().addTo(map),
    facilities: L.layerGroup().addTo(map),
    routes: L.layerGroup().addTo(map)
  };

  // DOM Elements
  const alertBanner = document.getElementById('alertBanner');
  const alertIcon = document.getElementById('alertIcon');
  const alertMsg = document.getElementById('alertMsg');

  const navRainVal = document.getElementById('navRainVal');
  const navTideVal = document.getElementById('navTideVal');
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

  async function init() {
    try {
      const nodesRes = await fetch('/api/nodes');
      state.nodes = await nodesRes.json();
      populateDropdowns(state.nodes);

      await fetchSimulation(12.0, 2.0, 100.0);
      await fetchFacilities();
      await fetchTelemetry();
      await calculateRoute();
    } catch (err) {
      console.error('Failed to initialize FloodGuard:', err);
    }
  }

  function populateDropdowns(nodes) {
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

    selStartNode.value = 'dadar_tt_circle';
    selEndNode.value = 'kem_hospital_gate';
  }

  async function fetchSimulation(rain, tide, pump) {
    try {
      const res = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rain_mm_hr: parseFloat(rain),
          tide_m: parseFloat(tide),
          pump_pct: parseFloat(pump)
        })
      });

      const data = await res.json();
      state.currentSim = data;
      updateSimulationUI(data);
      return data;
    } catch (err) {
      console.error('Simulation error:', err);
    }
  }

  function updateSimulationUI(data) {
    const { params, summary, nodes } = data;

    navRainVal.textContent = `${params.rain_mm_hr} mm/hr`;
    navTideVal.textContent = `${params.tide_m} m`;
    navRiverVal.textContent = `${summary.river_status} (${summary.river_stage_m}m)`;

    if (summary.river_status === 'DANGER') {
      navRiverVal.className = 'pill-val text-red';
    } else if (summary.river_status === 'WARNING') {
      navRiverVal.className = 'pill-val text-yellow';
    } else {
      navRiverVal.className = 'pill-val text-green';
    }

    if (summary.flooded_nodes > 1) {
      alertBanner.className = 'alert-banner danger';
      alertIcon.textContent = '●';
      alertMsg.textContent = `Warning: ${summary.flooded_nodes} intersections waterlogged. Hindmata underpass blocked. Emergency rerouting advised.`;
    } else if (summary.flooded_nodes === 1) {
      alertBanner.className = 'alert-banner warning';
      alertIcon.textContent = '▲';
      alertMsg.textContent = 'Notice: Minor water accumulation at Hindmata underpass. Normal traffic passing with caution.';
    } else {
      alertBanner.className = 'alert-banner normal';
      alertIcon.textContent = '✓';
      alertMsg.textContent = 'Normal traffic conditions. All roads and drainage channels clear.';
    }

    renderFloodCircles(nodes);
  }

  function renderFloodCircles(nodes) {
    layers.floodZones.clearLayers();

    nodes.forEach(node => {
      const isFlooded = node.depth_cm >= 15.0;
      const isSevere = node.depth_cm >= 45.0;

      const circleColor = isSevere ? '#ef4444' : (isFlooded ? '#d97706' : '#10b981');
      const radius = 45 + Math.min(130, node.depth_cm * 2.2);

      const circle = L.circle([node.lat, node.lon], {
        radius: radius,
        color: circleColor,
        fillColor: circleColor,
        fillOpacity: isFlooded ? 0.35 : 0.08,
        weight: isFlooded ? 1.5 : 1
      });

      const popupHtml = `
        <div class="custom-popup">
          <h4>${node.name}</h4>
          <p><strong>Ground Elevation:</strong> ${node.elevation_m}m</p>
          <p><strong>Surface Runoff:</strong> ${node.runoff_m3s} m³/s</p>
          <p><strong>Pipe Capacity:</strong> ${node.pipe_capacity_m3s} m³/s</p>
          <div class="depth-tag" style="background:${circleColor}18; color:${circleColor}; border:1px solid ${circleColor}44;">
            Water Depth: ${node.depth_cm} cm (${node.status})
          </div>
          <p style="margin-top:6px; font-size:11px; color:#64748b;">${node.notes}</p>
        </div>
      `;

      circle.bindPopup(popupHtml);
      layers.floodZones.addLayer(circle);

      // Clean point marker
      const marker = L.circleMarker([node.lat, node.lon], {
        radius: 5,
        color: '#ffffff',
        weight: 1.5,
        fillColor: circleColor,
        fillOpacity: 0.95
      }).bindPopup(popupHtml);

      layers.floodZones.addLayer(marker);
    });
  }

  async function fetchFacilities() {
    try {
      const res = await fetch('/api/facilities');
      const data = await res.json();
      state.facilities = data;
      renderFacilities(data);
    } catch (err) {
      console.error('Facilities error:', err);
    }
  }

  function renderFacilities(facilities) {
    layers.facilities.clearLayers();
    facilitiesList.innerHTML = '';

    facilities.forEach(f => {
      let iconSymbol = 'H';
      if (f.type === 'fire_station') iconSymbol = 'F';
      if (f.type === 'pumping_station') iconSymbol = 'P';
      if (f.type === 'substation') iconSymbol = 'E';
      if (f.type === 'shelter') iconSymbol = 'S';

      const statusColor = f.alert_level === 'CRITICAL' ? '#ef4444' : (f.alert_level === 'WARNING' ? '#d97706' : '#10b981');

      const icon = L.divIcon({
        className: 'facility-icon',
        html: `<div style="background:#ffffff; border:2px solid ${statusColor}; color:${statusColor}; border-radius:6px; width:26px; height:26px; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; box-shadow:0 1px 3px rgba(0,0,0,0.15);">${iconSymbol}</div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13]
      });

      const marker = L.marker([f.lat, f.lon], { icon }).bindPopup(`
        <div class="custom-popup">
          <h4>${f.name}</h4>
          <p><strong>Capacity:</strong> ${f.capacity}</p>
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
        <div style="font-size:10px; color:#94a3b8; margin-top:3px;">${f.capacity} • ${f.phone}</div>
      `;
      card.addEventListener('click', () => {
        map.flyTo([f.lat, f.lon], 16);
        marker.openPopup();
      });
      facilitiesList.appendChild(card);
    });
  }

  async function calculateRoute() {
    const start = selStartNode.value;
    const end = selEndNode.value;
    if (!start || !end || start === end) return;

    btnRecalculateRoute.textContent = 'Calculating route...';

    try {
      const res = await fetch('/api/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_node: start,
          end_node: end,
          vehicle_type: state.selectedVehicle
        })
      });

      const data = await res.json();
      state.currentRoutes = data;
      renderRoutes(data);
    } catch (err) {
      console.error('Route error:', err);
    } finally {
      btnRecalculateRoute.textContent = 'Calculate Flood-Safe Route';
    }
  }

  function renderRoutes(data) {
    layers.routes.clearLayers();
    const { standard_route, safe_route } = data;

    // Standard Route
    if (standard_route && standard_route.status === 'OK') {
      stdDist.textContent = standard_route.total_distance_km;
      stdTime.textContent = standard_route.total_time_mins;
      stdDepth.textContent = `${standard_route.max_water_depth_cm} cm`;

      if (standard_route.is_flooded) {
        stdBadge.className = 'badge';
        stdBadge.textContent = 'Waterlogged';
        stdDepth.className = 'text-red';
        stdNote.textContent = `Crosses ${standard_route.max_water_depth_cm}cm water at Hindmata underpass.`;
      } else {
        stdBadge.className = 'badge green';
        stdBadge.textContent = 'Clear';
        stdDepth.className = 'text-green';
        stdNote.textContent = 'All streets dry and passable.';
      }

      const stdCoords = standard_route.waypoints.map(w => [w.lat, w.lon]);
      const stdLine = L.polyline(stdCoords, {
        color: standard_route.is_flooded ? '#ef4444' : '#94a3b8',
        weight: 3,
        dashArray: standard_route.is_flooded ? '5, 5' : null,
        opacity: 0.8
      }).bindPopup(`<b>Standard Shortest Route</b><br>Max depth: ${standard_route.max_water_depth_cm} cm`);
      layers.routes.addLayer(stdLine);
    }

    // Safe Route
    if (safe_route && safe_route.status === 'OK') {
      safeDist.textContent = safe_route.total_distance_km;
      safeTime.textContent = safe_route.total_time_mins;
      safeDepth.textContent = `${safe_route.max_water_depth_cm} cm`;

      safeBadge.className = 'badge green';
      safeBadge.textContent = 'Safe Bypass';
      safeNote.textContent = 'Bypasses Hindmata via elevated Tilak Flyover corridor.';

      const safeCoords = safe_route.waypoints.map(w => [w.lat, w.lon]);
      const safeLine = L.polyline(safeCoords, {
        color: '#0284c7',
        weight: 4.5,
        opacity: 0.95
      }).bindPopup(`<b>FloodGuard Safe Route</b><br>0 cm flood exposure`);
      layers.routes.addLayer(safeLine);

      map.fitBounds(safeLine.getBounds(), { padding: [35, 35] });
      renderSteps(safe_route);
    } else {
      safeDist.textContent = '--';
      safeTime.textContent = '--';
      safeDepth.textContent = '>50 cm';
      safeBadge.className = 'badge';
      safeBadge.textContent = 'No Safe Path';
      safeNote.textContent = safe_route.message || 'Water too deep for this vehicle.';
      routeStepsList.innerHTML = `<li class="empty-step" style="color:#ef4444;">${safe_route.message}</li>`;
    }
  }

  function renderSteps(route) {
    routeStepsList.innerHTML = '';
    route.waypoints.forEach((wp) => {
      const li = document.createElement('li');
      li.innerHTML = `<strong>${wp.name}</strong> <span style="color:#94a3b8;">(${wp.elevation_m}m)</span>`;
      routeStepsList.appendChild(li);
    });
  }

  async function fetchTelemetry() {
    try {
      const res = await fetch('/api/telemetry');
      const data = await res.json();
      renderChart(data);
    } catch (err) {
      console.error('Telemetry error:', err);
    }
  }

  function renderChart(data) {
    const ctx = document.getElementById('riverChart').getContext('2d');
    const labels = data.chart_data.map(p => p.time);
    const values = data.chart_data.map(p => p.stage_m);

    if (riverChart) {
      riverChart.destroy();
    }

    riverChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'River Level (m)',
            data: values,
            borderColor: '#0284c7',
            backgroundColor: 'rgba(2, 132, 199, 0.08)',
            fill: true,
            tension: 0.25,
            pointRadius: 3
          },
          {
            label: 'Warning (3.9m)',
            data: labels.map(() => 3.9),
            borderColor: '#d97706',
            borderDash: [3, 3],
            pointRadius: 0
          },
          {
            label: 'Danger (4.8m)',
            data: labels.map(() => 4.8),
            borderColor: '#ef4444',
            borderDash: [3, 3],
            pointRadius: 0
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
          y: { min: 1.5, max: 5.5, ticks: { color: '#94a3b8', font: { size: 9 } }, grid: { color: '#f1f5f9' } }
        }
      }
    });
  }

  async function setDemoScenario(scenario) {
    btnCalm.classList.remove('active');
    btnStorm.classList.remove('active');
    btnSolution.classList.remove('active');

    if (scenario === 'calm') {
      btnCalm.classList.add('active');
      rngRain.value = 12;
      lblRainVal.textContent = '12 mm/hr (Light)';
      rngTide.value = 2.0;
      lblTideVal.textContent = '2.0 m (Normal)';
      rngPump.value = 100;
      lblPumpVal.textContent = '100% Operational';

      selPreset.value = 'ambulance_kem';
      selStartNode.value = 'dadar_tt_circle';
      selEndNode.value = 'kem_hospital_gate';
      setVehicle('ambulance');

      await fetchSimulation(12, 2.0, 100);
      await fetchFacilities();
      await fetchTelemetry();
      await calculateRoute();
      map.flyTo([19.0145, 72.8430], 14);
    }
    else if (scenario === 'storm') {
      btnStorm.classList.add('active');
      rngRain.value = 65;
      lblRainVal.textContent = '65 mm/hr (Downpour)';
      rngTide.value = 3.8;
      lblTideVal.textContent = '3.8 m (High Tide)';
      rngPump.value = 50;
      lblPumpVal.textContent = '50% (Surcharged)';

      await fetchSimulation(65, 3.8, 50);
      await fetchFacilities();
      await fetchTelemetry();
      await calculateRoute();
      map.flyTo([19.0142, 72.8427], 15);
    }
    else if (scenario === 'solution') {
      btnSolution.classList.add('active');
      await calculateRoute();
      switchTab('nav');
      map.flyTo([19.0135, 72.8420], 15);
    }
  }

  btnCalm.addEventListener('click', () => setDemoScenario('calm'));
  btnStorm.addEventListener('click', () => setDemoScenario('storm'));
  btnSolution.addEventListener('click', () => setDemoScenario('solution'));

  rngRain.addEventListener('input', (e) => {
    lblRainVal.textContent = `${e.target.value} mm/hr`;
  });
  rngTide.addEventListener('input', (e) => {
    lblTideVal.textContent = `${parseFloat(e.target.value).toFixed(1)} m`;
  });
  rngPump.addEventListener('input', (e) => {
    lblPumpVal.textContent = `${e.target.value}% Operational`;
  });

  btnRunSim.addEventListener('click', async () => {
    await fetchSimulation(rngRain.value, rngTide.value, rngPump.value);
    await fetchFacilities();
    await fetchTelemetry();
    await calculateRoute();
  });

  selPreset.addEventListener('change', (e) => {
    const val = e.target.value;
    if (val === 'ambulance_kem') {
      selStartNode.value = 'dadar_tt_circle';
      selEndNode.value = 'kem_hospital_gate';
      setVehicle('ambulance');
    } else if (val === 'commuter_parel') {
      selStartNode.value = 'kings_circle';
      selEndNode.value = 'parel_tt';
      setVehicle('car');
    } else if (val === 'evac_khalsa') {
      selStartNode.value = 'hindmata_junction';
      selEndNode.value = 'wadala_bridge';
      setVehicle('pedestrian');
    }
    calculateRoute();
  });

  btnRecalculateRoute.addEventListener('click', calculateRoute);

  document.querySelectorAll('.veh-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      setVehicle(btn.dataset.v);
      calculateRoute();
    });
  });

  function setVehicle(vType) {
    state.selectedVehicle = vType;
    document.querySelectorAll('.veh-btn').forEach(b => {
      if (b.dataset.v === vType) b.classList.add('active');
      else b.classList.remove('active');
    });
  }

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

  init();
});
