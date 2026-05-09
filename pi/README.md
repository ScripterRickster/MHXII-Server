# MHXII Keepalive on Raspberry Pi

This folder contains the files needed to make the keepalive pinger start automatically on boot.

## Files

- `mhxii-keepalive.service` - systemd service template
- `install_keepalive.sh` - installs and enables the service

## Setup

1. Clone this repo onto the Raspberry Pi.
2. Export your Render service URL.

```bash
export MHXII_SERVICE_URL=https://your-service.onrender.com
```

3. Run the installer from the repo root.

```bash
bash pi/install_keepalive.sh
```

The service will:

- start automatically on boot
- restart if it exits
- call `/keepalive` every 240 seconds by default

## Optional interval override

```bash
export KEEPALIVE_INTERVAL=180
bash pi/install_keepalive.sh
```

## Verify

```bash
sudo systemctl status mhxii-keepalive.service --no-pager
journalctl -u mhxii-keepalive.service -f
```
