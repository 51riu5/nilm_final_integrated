import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  Activity,
  Gauge,
  LoaderCircle,
  PlugZap,
  Radio,
  ShieldCheck,
  TriangleAlert,
  Wifi,
  WifiOff,
  Zap,
} from 'lucide-react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const WS_URL = import.meta.env.VITE_WS_URL || buildWsUrl(API_BASE)
const REFRESH_MS = 1000
const DEFAULT_WINDOW = 60
const MAX_BUFFERED_ROWS = 500
const PIE_COLORS = ['#135d66', '#f26419', '#2d9c95', '#f2a541', '#5f6caf', '#d7263d']

function buildWsUrl(apiBaseUrl) {
  try {
    const parsed = new URL(apiBaseUrl)
    const protocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${parsed.host}/ws/readings`
  } catch {
    return 'ws://localhost:8000/ws/readings'
  }
}

function readingKey(row) {
  return [
    row.device_id || 'unknown-device',
    row.received_at || 'no-received-at',
    row.timestamp || 'no-timestamp',
    row.meter_id || 'no-meter-id',
  ].join('|')
}

function disaggregationKey(row) {
  return [
    row.device_id || 'unknown-device',
    row.appliance_id || 'unknown-appliance',
    row.received_at || 'no-received-at',
    row.timestamp || 'no-timestamp',
  ].join('|')
}

function toEpoch(value) {
  const epoch = new Date(value || 0).getTime()
  return Number.isNaN(epoch) ? 0 : epoch
}

function mergeRows(previous, incoming, keyBuilder) {
  const map = new Map(previous.map((row) => [keyBuilder(row), row]))
  incoming.forEach((row) => {
    map.set(keyBuilder(row), row)
  })

  return [...map.values()]
    .sort(
      (a, b) =>
        toEpoch(a.timestamp || a.received_at) - toEpoch(b.timestamp || b.received_at),
    )
    .slice(-MAX_BUFFERED_ROWS)
}

async function fetchRecent(path, limit) {
  const response = await fetch(`${API_BASE}${path}?limit=${limit}`)
  if (!response.ok) {
    throw new Error(`failed_request_${response.status}`)
  }
  return response.json()
}

function formatTime(value) {
  if (!value) {
    return '--'
  }
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatDateTime(value) {
  if (!value) {
    return '--'
  }
  return new Date(value).toLocaleString()
}

function metricValue(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '--'
  }
  return Number(value).toFixed(digits)
}

function buildApplianceSnapshot(rows) {
  const latestPerAppliance = new Map()
  rows.forEach((row) => {
    const key = `${row.device_id}:${row.appliance_id}`
    const current = latestPerAppliance.get(key)
    const rowTs = toEpoch(row.timestamp || row.received_at)
    const currentTs = current ? toEpoch(current.timestamp || current.received_at) : 0
    if (!current || rowTs >= currentTs) {
      latestPerAppliance.set(key, row)
    }
  })

  return [...latestPerAppliance.values()]
    .map((row) => ({
      name: row.appliance_label || row.appliance_id,
      power_w: Number(row.power_w || 0),
      energy_kwh: Number(row.energy_kwh || 0),
    }))
    .sort((a, b) => b.power_w - a.power_w)
}

function App() {
  const [meterReadings, setMeterReadings] = useState([])
  const [disaggregatedReadings, setDisaggregatedReadings] = useState([])
  const [selectedSite, setSelectedSite] = useState('all')
  const [selectedDevice, setSelectedDevice] = useState('')
  const [limit, setLimit] = useState(DEFAULT_WINDOW)
  const [connectionState, setConnectionState] = useState('connecting')
  const [isSyncing, setIsSyncing] = useState(true)
  const [errorText, setErrorText] = useState('')
  const [lastSyncedAt, setLastSyncedAt] = useState(null)
  const reconnectTimerRef = useRef(null)

  const syncRecentData = useRef(async () => {})

  syncRecentData.current = async () => {
    try {
      setIsSyncing(true)
      const [recentReadings, recentDisaggregation] = await Promise.all([
        fetchRecent('/api/v1/readings/recent', 180),
        fetchRecent('/api/v1/disaggregation/recent', 500),
      ])

      setMeterReadings((prev) => mergeRows(prev, recentReadings, readingKey))
      setDisaggregatedReadings((prev) => mergeRows(prev, recentDisaggregation, disaggregationKey))
      setLastSyncedAt(new Date().toISOString())
      setErrorText('')
    } catch {
      setErrorText('Unable to sync from backend. Confirm the API is running and reachable.')
    } finally {
      setIsSyncing(false)
    }
  }

  useEffect(() => {
    syncRecentData.current()
    const interval = setInterval(() => {
      syncRecentData.current()
    }, REFRESH_MS)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    let isActive = true
    let socket

    const connect = () => {
      if (!isActive) {
        return
      }

      setConnectionState('connecting')
      socket = new WebSocket(WS_URL)

      socket.onopen = () => {
        setConnectionState('live')
      }

      socket.onmessage = (event) => {
        try {
          const next = JSON.parse(event.data)
          setMeterReadings((prev) => mergeRows(prev, [next], readingKey))
          setLastSyncedAt(new Date().toISOString())
          setErrorText('')
        } catch {
          setErrorText('Received malformed data from WebSocket stream.')
        }
      }

      socket.onerror = () => {
        setConnectionState('offline')
      }

      socket.onclose = () => {
        if (!isActive) {
          return
        }
        setConnectionState('offline')
        reconnectTimerRef.current = setTimeout(connect, 2500)
      }
    }

    connect()

    return () => {
      isActive = false
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
      if (socket && socket.readyState <= 1) {
        socket.close()
      }
    }
  }, [])

  const sites = useMemo(() => {
    const values = new Set(meterReadings.map((row) => row.site_id).filter(Boolean))
    return [...values]
  }, [meterReadings])

  const devices = useMemo(() => {
    const map = new Map()
    meterReadings.forEach((row) => {
      if (!map.has(row.device_id)) {
        map.set(row.device_id, {
          device_id: row.device_id,
          meter_id: row.meter_id,
          site_id: row.site_id,
        })
      }
    })
    return [...map.values()]
  }, [meterReadings])

  const deviceOptions = useMemo(() => {
    return devices.filter((device) => selectedSite === 'all' || device.site_id === selectedSite)
  }, [devices, selectedSite])

  useEffect(() => {
    if (deviceOptions.length === 0) {
      setSelectedDevice('')
      return
    }

    const exists = deviceOptions.some((device) => device.device_id === selectedDevice)
    if (!exists) {
      setSelectedDevice(deviceOptions[0].device_id)
    }
  }, [deviceOptions, selectedDevice])

  const filteredReadings = useMemo(() => {
    if (!selectedDevice) {
      return []
    }
    return meterReadings.filter((row) => row.device_id === selectedDevice).slice(-limit)
  }, [meterReadings, selectedDevice, limit])

  const filteredDisaggregation = useMemo(() => {
    if (!selectedDevice) {
      return []
    }
    return disaggregatedReadings
      .filter((row) => row.device_id === selectedDevice)
      .slice(-(limit * 8))
  }, [disaggregatedReadings, selectedDevice, limit])

  const chartSeries = useMemo(
    () =>
      filteredReadings.map((row) => ({
        ...row,
        label: formatTime(row.timestamp || row.received_at),
      })),
    [filteredReadings],
  )

  const applianceTotals = useMemo(
    () => buildApplianceSnapshot(filteredDisaggregation),
    [filteredDisaggregation],
  )

  const latestReading = filteredReadings.at(-1)

  const alertItems = useMemo(() => {
    if (!latestReading) {
      return []
    }
    const alerts = []
    if (latestReading.power_w > 3200) {
      alerts.push('High demand spike detected, check HVAC and kettle overlap.')
    }
    if (latestReading.power_factor < 0.82) {
      alerts.push('Low power factor observed, investigate inductive loads.')
    }
    if (latestReading.frequency_hz < 49.9 || latestReading.frequency_hz > 50.1) {
      alerts.push('Grid frequency drift noticed outside preferred range.')
    }
    return alerts
  }, [latestReading])

  const activeAppliances = useMemo(
    () => applianceTotals.filter((row) => row.power_w > 200).length,
    [applianceTotals],
  )

  const energyTotal = Number(latestReading?.energy_kwh || 0)

  const streamStatusLabel =
    connectionState === 'live'
      ? 'WebSocket live'
      : connectionState === 'connecting'
        ? 'Connecting stream'
        : 'Stream reconnecting'

  const showEmptyState = !isSyncing && filteredReadings.length === 0
  const tableRows = useMemo(() => {
    if (filteredReadings.length > 0) {
      return filteredReadings
    }

    // Fallback so the table still shows incoming stream rows even before a device is selected.
    return meterReadings.slice(-Math.max(limit, 8))
  }, [filteredReadings, meterReadings, limit])

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">NILM Smart Meter Control Room</p>
          <h1>Live Energy Operations Dashboard</h1>
          <p className="subtext">
            Synced with backend ingest endpoints and 1-second telemetry cadence from the microprocessor.
          </p>
          <p className="backend-meta">
            API: <code>{API_BASE}</code>
          </p>
        </div>
        <div className="live-chip" role="status" aria-live="polite">
          <span className={`dot ${connectionState === 'live' ? 'on' : 'off'}`}></span>
          {connectionState === 'live' ? <Wifi size={14} /> : <WifiOff size={14} />}
          {streamStatusLabel}
        </div>
      </header>

      <section className="controls panel">
        <label>
          Site
          <select
            value={selectedSite}
            onChange={(e) => {
              const nextSite = e.target.value
              setSelectedSite(nextSite)
              const firstDevice = devices.find(
                (d) => nextSite === 'all' || d.site_id === nextSite,
              )
              if (firstDevice) {
                setSelectedDevice(firstDevice.device_id)
              }
            }}
          >
            <option value="all">All Sites</option>
            {sites.map((site) => (
              <option key={site} value={site}>
                {site}
              </option>
            ))}
          </select>
        </label>
        <label>
          Device
          <select value={selectedDevice} onChange={(e) => setSelectedDevice(e.target.value)}>
            {deviceOptions.map((device) => (
              <option key={device.device_id} value={device.device_id}>
                {device.device_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Window ({limit} points)
          <input
            type="range"
            min="20"
            max="120"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          />
        </label>
        <button className="live-btn" onClick={() => syncRecentData.current()}>
          Refresh Now
        </button>
      </section>

      {errorText ? (
        <section className="panel status status-error" role="alert">
          <TriangleAlert size={16} /> {errorText}
        </section>
      ) : null}

      <section className="panel status status-info">
        {isSyncing ? <LoaderCircle size={16} className="spin" /> : <Radio size={16} />}
        <span>Sync cadence: every 1 second</span>
        <span>Last update: {formatDateTime(lastSyncedAt)}</span>
      </section>

      <section className="kpi-grid">
        <article className="panel kpi">
          <Zap size={18} />
          <h3>Instant Power</h3>
          <p>{metricValue(latestReading?.power_w, 0)} W</p>
        </article>
        <article className="panel kpi">
          <PlugZap size={18} />
          <h3>Energy (kWh)</h3>
          <p>{metricValue(energyTotal, 3)}</p>
        </article>
        <article className="panel kpi">
          <Gauge size={18} />
          <h3>Power Factor</h3>
          <p>{metricValue(latestReading?.power_factor, 2)}</p>
        </article>
        <article className="panel kpi">
          <Activity size={18} />
          <h3>Active Loads</h3>
          <p>{activeAppliances}</p>
        </article>
      </section>

      <section className="grid-2">
        <article className="panel chart-card">
          <h2>Demand and Quality Trend</h2>
          <ResponsiveContainer width="100%" height={310}>
            <LineChart data={chartSeries}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d7e5e8" />
              <XAxis dataKey="label" minTickGap={20} />
              <YAxis yAxisId="left" orientation="left" />
              <YAxis yAxisId="right" orientation="right" />
              <Tooltip />
              <Legend />
              <Line yAxisId="left" type="monotone" dataKey="power_w" stroke="#0f766e" strokeWidth={2} dot={false} name="Power (W)" />
              <Line yAxisId="right" type="monotone" dataKey="power_factor" stroke="#ef4444" strokeWidth={2} dot={false} name="Power Factor" />
              <Line yAxisId="right" type="monotone" dataKey="frequency_hz" stroke="#0ea5e9" strokeWidth={2} dot={false} name="Freq (Hz)" />
            </LineChart>
          </ResponsiveContainer>
        </article>

        <article className="panel chart-card">
          <h2>Energy and Voltage Profile</h2>
          <ResponsiveContainer width="100%" height={310}>
            <AreaChart data={chartSeries}>
              <defs>
                <linearGradient id="energy" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f2a541" stopOpacity={0.55} />
                  <stop offset="95%" stopColor="#f2a541" stopOpacity={0.06} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#d7e5e8" />
              <XAxis dataKey="label" minTickGap={20} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Area type="monotone" dataKey="energy_kwh" fill="url(#energy)" stroke="#f2a541" strokeWidth={2} name="Energy (kWh)" />
              <Line type="monotone" dataKey="voltage_v" stroke="#5f6caf" strokeWidth={2} dot={false} name="Voltage (V)" />
            </AreaChart>
          </ResponsiveContainer>
        </article>
      </section>

      <section className="grid-2">
        <article className="panel chart-card">
          <h2>Appliance Consumption Mix</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={applianceTotals.slice(0, 6)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d7e5e8" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="power_w" radius={[8, 8, 0, 0]}>
                {applianceTotals.slice(0, 6).map((row, index) => (
                  <Cell key={row.name} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </article>

        <article className="panel chart-card">
          <h2>Load Share Snapshot</h2>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={applianceTotals.slice(0, 6)} dataKey="power_w" nameKey="name" outerRadius={95} innerRadius={56}>
                {applianceTotals.slice(0, 6).map((row, index) => (
                  <Cell key={row.name} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </article>
      </section>

      <section className="grid-2">
        <article className="panel">
          <h2>Recent Meter Stream</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Device</th>
                  <th>Time</th>
                  <th>Power (W)</th>
                  <th>Voltage (V)</th>
                  <th>Current (A)</th>
                  <th>PF</th>
                </tr>
              </thead>
              <tbody>
                {tableRows.slice(-8).reverse().map((row) => (
                  <tr key={readingKey(row)}>
                    <td>{row.device_id || '--'}</td>
                    <td>{formatTime(row.timestamp || row.received_at)}</td>
                    <td>{metricValue(row.power_w, 0)}</td>
                    <td>{metricValue(row.voltage_v, 1)}</td>
                    <td>{metricValue(row.current_a, 2)}</td>
                    <td>{metricValue(row.power_factor, 2)}</td>
                  </tr>
                ))}
                {showEmptyState ? (
                  <tr>
                    <td colSpan={6}>No readings available yet for this device.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel insight">
          <h2>Operational Insights</h2>
          {alertItems.length === 0 ? (
            <p className="ok"><ShieldCheck size={16} /> No critical alerts. System behavior is stable.</p>
          ) : (
            alertItems.map((item) => (
              <p key={item} className="warn">
                <TriangleAlert size={16} /> {item}
              </p>
            ))
          )}
          <p className="meta">
            Source fields: <code>device_id</code>, <code>meter_id</code>, <code>site_id</code>, <code>voltage_v</code>, <code>current_a</code>, <code>power_w</code>, <code>energy_kwh</code>, <code>frequency_hz</code>, <code>power_factor</code>.
          </p>
        </article>
      </section>
    </div>
  )
}

export default App
