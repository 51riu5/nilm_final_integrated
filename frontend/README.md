# NILM Frontend Dashboard

React + Vite dashboard connected to the NILM FastAPI backend.

## What It Shows

- Real-time meter stream from `ws://.../ws/readings`
- 1-second sync from:
	- `GET /api/v1/readings/recent`
	- `GET /api/v1/disaggregation/recent`
- KPI cards for power, energy, power factor, and active loads
- Trend charts for power quality and energy profile
- Appliance split visualizations and recent reading table

## Backend Fields Used

- `device_id`
- `meter_id`
- `site_id`
- `timestamp`
- `received_at`
- `voltage_v`
- `current_a`
- `power_w`
- `energy_kwh`
- `frequency_hz`
- `power_factor`
- Disaggregation: `appliance_id`, `appliance_label`, `power_w`, `energy_kwh`

## Run Locally

```bash
npm install
npm run dev
```

## Optional Environment Variables

Create `.env` inside `frontend/` if backend is not running at `http://localhost:8000`:

```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws/readings
```

If `VITE_WS_URL` is not provided, the app auto-derives it from `VITE_API_BASE_URL`.

## Build

```bash
npm run build
```
