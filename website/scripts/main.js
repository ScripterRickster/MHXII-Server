document.addEventListener('DOMContentLoaded', function () {
	const clock = document.getElementById('clock');
	const robotToggle = document.getElementById('robotToggle');
	const piUrlInput = document.getElementById('piUrlInput');
	const piStatus = document.getElementById('piStatus');
	const piError = document.getElementById('piError');
	let map = null;
	let markers = [];
	let robotState = 'off';
	let piConnected = false;
	let piUrl = localStorage.getItem('piUrl') || '';
	let vidTimer = null;
	let locTimer = null;
	let robTimer = null;

	// Load and display PI URL
	function loadPi() {
		if (piUrlInput) {
			piUrlInput.value = piUrl;
		}
		if (!piUrl) {
			updatePiStat('disconnected');
			setPiErr('');
		}
	}

	function setPiErr(message) {
		if (!piError) return;
		piError.textContent = message || '';
	}

	// Update Pi connection status indicator
	function updatePiStat(status) {
		if (!piStatus) return;
		piStatus.setAttribute('data-status', status);
		if (status === 'connected') {
			piStatus.title = 'Connected to Pi';
			piStatus.textContent = '🟢';
			piConnected = true;
			setPiErr('');
			if (robotToggle) robotToggle.disabled = false;
			if (!vidTimer) {
				updateVidFeed();
				vidTimer = setInterval(updateVidFeed, 2000);
			}
			if (!locTimer) {
				fetchLocations();
				locTimer = setInterval(fetchLocations, 5000);
			}
			if (!robTimer) {
				getRobStat();
				robTimer = setInterval(getRobStat, 5000);
			}
		} else if (status === 'connecting') {
			piStatus.title = 'Connecting to Pi...';
			piStatus.textContent = '🟡';
			piConnected = false;
			if (robotToggle) robotToggle.disabled = true;
			if (vidTimer) {
				clearInterval(vidTimer);
				vidTimer = null;
			}
			if (locTimer) {
				clearInterval(locTimer);
				locTimer = null;
			}
			if (robTimer) {
				clearInterval(robTimer);
				robTimer = null;
			}
		} else {
			piStatus.title = 'Not connected to Pi (check URL or network)';
			piStatus.textContent = '⚫';
			piConnected = false;
			if (robotToggle) robotToggle.disabled = true;
			if (vidTimer) {
				clearInterval(vidTimer);
				vidTimer = null;
			}
			if (locTimer) {
				clearInterval(locTimer);
				locTimer = null;
			}
			if (robTimer) {
				clearInterval(robTimer);
				robTimer = null;
			}
		}
	}

	// Check Pi connectivity
	async function checkPiConn() {
		if (!piUrl) return false;
		updatePiStat('connecting');
		try {
			const res = await fetch('/robot/status', { signal: AbortSignal.timeout(5000) });
			if (res.ok) {
				updatePiStat('connected');
				return true;
			}
		} catch (e) {
			console.warn('Pi connection check failed:', e);
		}
		updatePiStat('disconnected');
		setPiErr('Failed to connect to Pi');
		return false;
	}

	// Save PI URL and check connection
	async function savePi() {
		if (piUrlInput) {
			piUrl = piUrlInput.value.trim();
			if (!piUrl) {
				localStorage.removeItem('piUrl');
				piConnected = false;
				updatePiStat('disconnected');
				setPiErr('');
				if (vidTimer) {
					clearInterval(vidTimer);
					vidTimer = null;
				}
				if (locTimer) {
					clearInterval(locTimer);
					locTimer = null;
				}
				if (robTimer) {
					clearInterval(robTimer);
					robTimer = null;
				}
				return;
			}
			localStorage.setItem('piUrl', piUrl);
			// Update server
			try {
				await fetch('/robot/set-pi-url', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ pi_url: piUrl })
				});
			} catch (e) {
				console.warn('Could not update server Pi URL:', e);
			}
			// Check connection to new URL
			const connected = await checkPiConn();
			if (!connected) {
				setPiErr('Failed to connect to Pi');
			}
		}
	}

	if (piUrlInput) {
		piUrlInput.addEventListener('change', savePi);
		piUrlInput.addEventListener('blur', savePi);
	}

	function updateClock() {
		if (!clock) return;
		const now = new Date();
		clock.textContent = now.toLocaleTimeString([], {
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit'
		});
	}

	// Robot control
	async function getRobStat() {
		if (!piConnected) return;
		try {
			const res = await fetch('/robot/status', { signal: AbortSignal.timeout(5000) });
			if (!res.ok) return;
			const data = await res.json();
			robotState = data.state || 'off';
			updRobUI();
		} catch (e) {
			console.warn('getRobStat error', e);
			checkPiConn(); // Re-check if still connected
		}
	}

	function updRobUI() {
		if (!robotToggle) return;
		robotToggle.setAttribute('data-state', robotState);
		const text = robotToggle.querySelector('.robot-text');
		if (text) {
			text.textContent = `Robot: ${robotState.toUpperCase()}`;
		}
	}

	async function togRob() {
		if (!piConnected) return;
		try {
			robotToggle.style.opacity = '0.6';
			const res = await fetch('/robot/toggle', { 
				method: 'POST',
				signal: AbortSignal.timeout(5000)
			});
			if (!res.ok) return;
			const data = await res.json();
			robotState = data.state || 'off';
			if (data.pi_error) {
				console.warn('Pi error:', data.pi_error);
				robotToggle.title = data.pi_error;
				setTimeout(() => { robotToggle.title = ''; }, 3000);
				checkPiConn(); // Re-check connection
			}
			updRobUI();
		} catch (e) {
			console.warn('togRob error', e);
			robotToggle.title = 'Connection failed';
			setTimeout(() => { robotToggle.title = ''; }, 3000);
			checkPiConn(); // Re-check connection
		} finally {
			robotToggle.style.opacity = '1';
		}
	}

	if (robotToggle) {
		robotToggle.addEventListener('click', togRob);
	}

	// Video feed display
	function updateVidFeed() {
		const videoImg = document.getElementById('videoImage');
		if (!videoImg) return;
		// Add cache bust parameter to always get fresh image
		const timestamp = new Date().getTime();
		videoImg.src = `/feed/latest.png?t=${timestamp}`;
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
		if (!map) return;
		markers.forEach(m => map.removeLayer(m));
		markers = [];
	}

	function updateLocList(locations) {
		const list = document.getElementById('locationsList');
		if (!list) return;
		list.innerHTML = '';
		locations.forEach(loc => {
			const el = document.createElement('div');
			el.className = 'loc-item';
			const time = loc.timestamp || '';
			el.textContent = `${loc.device || 'trash'} — ${loc.lat.toFixed(6)}, ${loc.lon.toFixed(6)} — ${time}`;
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
			updateLocList(locs.reverse());
		} catch (e) {
			console.warn('fetchLocations error', e);
			const list = document.getElementById('locationsList');
			if (list && !list.dataset.errorShown) {
				list.dataset.errorShown = '1';
				list.innerHTML = '<div class="loc-item">Locations unavailable right now</div>';
			}
		}
	}

	updateClock();
	setInterval(updateClock, 1000);
	loadPi();
	initMap();
	
	// Only auto-check if a Pi URL was previously entered
	if (piUrl) {
		checkPiConn();
		setInterval(checkPiConn, 10000); // Re-check every 10 seconds
	}
});
