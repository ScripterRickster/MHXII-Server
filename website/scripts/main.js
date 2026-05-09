document.addEventListener('DOMContentLoaded', function () {
	const display = document.getElementById('display');
	const toggleBtn = document.getElementById('toggleBtn');
	const status = document.getElementById('status');
	let mode = 'image';
	let intervalId = null;

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
});
