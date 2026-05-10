document.addEventListener('DOMContentLoaded', function () {
	const clock = document.getElementById('clock');
	const faqButton = document.getElementById('faqButton');
	const faqModal = document.getElementById('faqModal');
	const faqCloseButton = document.getElementById('faqCloseButton');
	const robotToggle = document.getElementById('robotToggle');
	const robotShutdown = document.getElementById('robotShutdown');
	const piStatus = document.getElementById('piStatus');
	const robotStateLabel = document.getElementById('robotStateLabel');
	const robotBatteryLabel = document.getElementById('robotBatteryLabel');
	const robotDesiredLabel = document.getElementById('robotDesiredLabel');
	const robotShutdownLabel = document.getElementById('robotShutdownLabel');
	const robotLastSeenLabel = document.getElementById('robotLastSeenLabel');
	const robotMessageLabel = document.getElementById('robotMessageLabel');
	let map = null;
	let markers = [];
	let robotState = 'off';
	let desiredRobotState = 'off';
	let shutdownRequested = false;
	let robotBattery = null;
	let robotLastSeen = 0;
	let robotMessage = '';
	let piConnected = false;
	let vidTimer = null;
	let locTimer = null;
	let robTimer = null;

	function openFaq() {
		if (!faqModal) return;
		faqModal.classList.add('is-open');
		faqModal.setAttribute('aria-hidden', 'false');
		document.body.classList.add('faq-open');
	}

	function closeFaq() {
		if (!faqModal) return;
		faqModal.classList.remove('is-open');
		faqModal.setAttribute('aria-hidden', 'true');
		document.body.classList.remove('faq-open');
	}

	function updatePiStat() {
		if (!piStatus) return;
		if (piConnected) {
			piStatus.setAttribute('data-status', 'connected');
			piStatus.title = 'Connected to Pi (fresh Pi updates)';
			piStatus.textContent = '🟢';
		} else {
			piStatus.setAttribute('data-status', 'disconnected');
			piStatus.title = 'Not connected to Pi';
			piStatus.textContent = '⚫';
		}
	}


	function updateClock() {
		if (!clock) return;
		const now = new Date();
		const clockTime = document.getElementById('clockTime');
		const clockDate = document.getElementById('clockDate');
		if (clockTime) {
			clockTime.textContent = now.toLocaleTimeString([], {
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit'
			});
		}
		if (clockDate) {
			clockDate.textContent = now.toLocaleDateString('en-GB');
		}
	}

	// Robot control - get status and record request outcome
	async function getRobStat() {
		try {
			const res = await fetch('/robot/status', { signal: AbortSignal.timeout(10000) });
			if (!res.ok) {
				piConnected = false;
				updatePiStat();
				return;
			}
			const data = await res.json();
			robotState = data.state || 'off';
			desiredRobotState = data.desired_state || desiredRobotState;
			shutdownRequested = Boolean(data.shutdown_requested);
			robotBattery = data.battery;
			robotLastSeen = Number(data.pi_last_seen || 0);
			robotMessage = data.message || '';
			piConnected = Boolean(data.pi_connected);
			updRobUI();
			updTelemetryUI();
			updatePiStat();
			syncVidTimer();
		} catch (e) {
			if (e && e.name !== 'TimeoutError' && e.name !== 'AbortError') {
				console.warn('getRobStat error', e);
			}
			piConnected = false;
			updTelemetryUI();
			updatePiStat();
			syncVidTimer();
		}
	}

	function updRobUI() {
		if (!robotToggle) return;
		robotToggle.setAttribute('data-state', desiredRobotState);
		const text = robotToggle.querySelector('.robot-text');
		if (text) {
			text.textContent = desiredRobotState === 'on' ? 'TURN OFF' : 'TURN ON';
		}
	}

	function formatLastSeen(epochSeconds) {
		if (!epochSeconds) return '--';
		const ms = epochSeconds * 1000;
		if (!Number.isFinite(ms)) return '--';
		const diffSec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
		if (diffSec < 60) return `${diffSec}s ago`;
		const mins = Math.floor(diffSec / 60);
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		return `${hrs}h ago`;
	}

	function updTelemetryUI() {
		if (robotStateLabel) robotStateLabel.textContent = String(robotState || 'unknown').toUpperCase();
		if (robotDesiredLabel) robotDesiredLabel.textContent = String(desiredRobotState || 'off').toUpperCase();
		if (robotShutdownLabel) robotShutdownLabel.textContent = shutdownRequested ? 'Yes' : 'No';
		if (robotBatteryLabel) {
			const val = Number(robotBattery);
			robotBatteryLabel.textContent = Number.isFinite(val) ? `${Math.max(0, Math.min(100, Math.round(val)))}%` : '--%';
		}
		if (robotLastSeenLabel) robotLastSeenLabel.textContent = formatLastSeen(robotLastSeen);
		if (robotMessageLabel) robotMessageLabel.textContent = robotMessage || 'No status message';
	}

	function showTransientRobotMessage(message, type = 'info') {
		if (!robotMessageLabel) return;
		window.clearTimeout(showTransientRobotMessage._timer);
		robotMessageLabel.classList.remove('is-fading');
		robotMessageLabel.dataset.messageType = type;
		robotMessageLabel.textContent = message;
		showTransientRobotMessage._timer = window.setTimeout(() => {
			if (!robotMessageLabel) return;
			robotMessageLabel.classList.add('is-fading');
			window.setTimeout(() => {
				if (!robotMessageLabel) return;
				robotMessageLabel.classList.remove('is-fading');
				robotMessageLabel.removeAttribute('data-message-type');
				robotMessageLabel.textContent = robotMessage || 'No status message';
			}, 420);
		}, 2400);
	}

	// Toggle desired state on the server; Pi picks it up by polling /robot/pi/commands
	async function togRob() {
		const startingUp = desiredRobotState !== 'on';
		try {
			robotToggle.style.opacity = '0.6';
			showTransientRobotMessage(
				startingUp ? 'Sending startup command to robot...' : 'Sending stop command to robot...',
				'pending'
			);
			const res = await fetch('/robot/toggle', {
				method: 'POST',
				signal: AbortSignal.timeout(5000)
			});
			if (!res.ok) {
				robotToggle.title = 'Toggle failed';
				setTimeout(() => { robotToggle.title = ''; }, 3000);
				showTransientRobotMessage('Toggle request failed', 'error');
				return;
			}
			const data = await res.json();
			desiredRobotState = data.desired_state || desiredRobotState;
			updRobUI();

			// Wait for the Pi to confirm the state change, with a timeout
			const targetState = desiredRobotState; // 'on' or 'off'
			const ON_STATES  = ['on', 'starting'];
			const OFF_STATES = ['off', 'stopping'];
			const POLL_INTERVAL = 2000;
			const TIMEOUT_MS = 30000;
			const started = Date.now();

			showTransientRobotMessage(
				startingUp ? 'Waiting for robot to start up...' : 'Waiting for robot to stop...',
				'pending'
			);

			await new Promise((resolve) => {
				async function poll() {
					await getRobStat();
					const reached = targetState === 'on' ? ON_STATES.includes(robotState) : OFF_STATES.includes(robotState);
					if (reached) {
						showTransientRobotMessage(
							startingUp ? 'Robot is now ON' : 'Robot is now OFF',
							'success'
						);
						resolve();
						return;
					}
					if (Date.now() - started > TIMEOUT_MS) {
						showTransientRobotMessage(
							startingUp
								? 'Robot did not respond in time — check connection'
								: 'Robot did not stop in time — check connection',
							'error'
						);
						resolve();
						return;
					}
					setTimeout(poll, POLL_INTERVAL);
				}
				poll();
			});

		} catch (e) {
			console.warn('togRob error', e);
			robotToggle.title = 'Connection failed';
			setTimeout(() => { robotToggle.title = ''; }, 3000);
			showTransientRobotMessage('Robot action failed', 'error');
		} finally {
			robotToggle.style.opacity = '1';
		}
	}

	async function requestShutdown() {
		if (!robotShutdown) return;
		try {
			robotShutdown.style.opacity = '0.6';
			const res = await fetch('/robot/shutdown', {
				method: 'POST',
				signal: AbortSignal.timeout(5000)
			});
			if (!res.ok) {
				robotShutdown.title = 'Shutdown request failed';
				setTimeout(() => { robotShutdown.title = ''; }, 3000);
				return;
			}
		} catch (e) {
			console.warn('requestShutdown error', e);
			robotShutdown.title = 'Connection failed';
			setTimeout(() => { robotShutdown.title = ''; }, 3000);
		} finally {
			robotShutdown.style.opacity = '1';
		}
	}

	if (robotToggle) {
		robotToggle.addEventListener('click', togRob);
	}
	if (robotShutdown) {
		robotShutdown.addEventListener('click', requestShutdown);
	}

	if (faqButton) {
		faqButton.addEventListener('click', openFaq);
	}
	if (faqCloseButton) {
		faqCloseButton.addEventListener('click', closeFaq);
	}
	if (faqModal) {
		faqModal.addEventListener('click', function (event) {
			if (event.target && event.target.hasAttribute('data-faq-close')) {
				closeFaq();
			}
		});
	}
	document.addEventListener('keydown', function (event) {
		if (event.key === 'Escape') {
			closeFaq();
		}
	});

	// Video feed display — only runs when Pi is connected
	function updateVidFeed() {
		if (!piConnected) return;
		const videoImg = document.getElementById('videoImage');
		if (!videoImg) return;
		const url = `/feed/latest.png?t=${Date.now()}`;
		const offscreen = new Image();
		offscreen.onload = () => { videoImg.src = url; };
		offscreen.src = url;
	}

	function syncVidTimer() {
		if (piConnected && !vidTimer) {
			updateVidFeed();
			vidTimer = setInterval(updateVidFeed, 2000);
		} else if (!piConnected && vidTimer) {
			clearInterval(vidTimer);
			vidTimer = null;
		}
	}

	// Map and locations
	function initMap() {
		if (typeof L === 'undefined') {
			console.warn('Leaflet not loaded yet, will retry');
			// Retry once Leaflet is available
			setTimeout(() => {
				if (typeof L !== 'undefined' && !map) {
					initMap();
				}
			}, 500);
			return;
		}
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

	// Initialization
	updateClock();
	setInterval(updateClock, 1000);
	initMap();
	if (faqModal) {
		faqModal.setAttribute('aria-hidden', 'true');
	}
	
	if (!locTimer) {
		fetchLocations();
		locTimer = setInterval(fetchLocations, 5000);
	}

	// Start checking robot status immediately - this drives the connection indicator.
	// The server marks pi_connected based on freshness of Pi updates.
	getRobStat();
	robTimer = setInterval(getRobStat, 7000);
});