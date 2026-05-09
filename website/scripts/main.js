document.addEventListener('DOMContentLoaded', function () {
	const display = document.getElementById('display');
	const toggleBtn = document.getElementById('toggleBtn');
	const status = document.getElementById('status');
	let mode = 'image';
	let intervalId = null;
	let map = null;
	let markers = [];

	function showImage() {
		display.style.backgroundImage = "url('/images/bg.png')";
		status.textContent = 'Mode: Project Image';
	}

	function startFeed() {
		async function update() {
			// set background to the PNG endpoint (cache-busted)
			display.style.backgroundImage = `url('/feed/latest.png?ts=${Date.now()}')`;
		}
		update();
		intervalId = setInterval(update, 1000);
		status.textContent = 'Mode: Robot Feed (polling)';
	}

	// Map and locations
	function initMap() {
		try {
			map = L.map('map', { zoomControl: true }).setView([0, 0], 2);
			L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
				maxZoom: 19,
				attribution: '&copy; OpenStreetMap contributors'
			}).addTo(map);
		} catch (e) {
			console.warn('Leaflet not available', e);
		}
	}

	function clearMarkers() {
		markers.forEach(m => map.removeLayer(m));
		markers = [];
	}

	function updateLocationsList(locations) {
		const list = document.getElementById('locationsList');
		if (!list) return;
		list.innerHTML = '';
		locations.forEach(loc => {
			const el = document.createElement('div');
			el.className = 'loc-item';
			const time = loc.timestamp || '';
			el.textContent = `${loc.device || 'device'} — ${loc.lat.toFixed(6)}, ${loc.lon.toFixed(6)} — ${time}`;
			list.appendChild(el);
		});
	}

	async function fetchLocations() {
		try {
			const res = await fetch('/locations?limit=200');
			if (!res.ok) return;
			const data = await res.json();
			const locs = (data.locations || []).slice().reverse(); // oldest->newest
			if (map) {
				clearMarkers();
				locs.forEach(l => {
					const m = L.circleMarker([l.lat, l.lon], { radius: 6, color: '#12e0d6', fill: true, fillOpacity: 0.9 }).addTo(map);
					markers.push(m);
				});
				if (locs.length) {
					const last = locs[locs.length - 1];
					map.setView([last.lat, last.lon], 14);
				}
			}
			updateLocationsList(locs.reverse());
		} catch (e) {
			console.warn('fetchLocations error', e);
			const list = document.getElementById('locationsList');
			if (list && !list.dataset.errorShown) {
				list.dataset.errorShown = '1';
				list.innerHTML = '<div class="loc-item">Locations unavailable right now</div>';
			}
		}
	}

	toggleBtn.addEventListener('click', function () {
		if (mode === 'image') {
			mode = 'feed';
			toggleBtn.textContent = 'Show Project Image';
			startFeed();
		} else {
			mode = 'image';
			toggleBtn.textContent = 'Show Robot Feed';
			if (intervalId) {
				clearInterval(intervalId);
				intervalId = null;
			}
			showImage();
		}
	});

	// initialize
	showImage();
	initMap();
	fetchLocations();
	setInterval(fetchLocations, 5000);
});
