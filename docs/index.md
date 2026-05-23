# Universal Reader — Documentation

Welcome to the Universal Reader documentation.  
Select a topic below to get started.

## Contents

| Document | Description |
|----------|-------------|
| [Setup Guide](setup.md) | Step-by-step installation and first-run instructions |
| [Configuration Reference](configuration.md) | All environment variables explained |
| [Hardware Wiring](hardware.md) | GPIO pin mapping and wiring diagrams |
| [REST API Reference](api.md) | Full reference for every `/api/v1/*` endpoint |
| [WebSocket Protocol](websocket.md) | How the reader talks to an Inventory server |

## Quick start (TL;DR)

```bash
# 1. Clone and install
git clone https://github.com/afonsoingles/universal-reader.git
cd universal-reader
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync

# 2. Configure
cp .env.example .env
nano .env          # set INVENTORY_WS_URL, INVENTORY_API_KEY, DASHBOARD_PASSWORD

# 3. Run
uv run universal-reader
```

Open `http://<pi-ip>:5050` in your browser, log in with the password from `.env`, and
you're up and running.

For production deployments, see the [systemd service section](setup.md#run-as-a-systemd-service) in the setup guide.
