import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
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
  BrainCircuit,
  Gauge,
  LoaderCircle,
  Lightbulb,
  PlugZap,
  Radio,
  ShieldCheck,
  ToggleLeft,
  ToggleRight,
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

const APPLIANCE_COLORS = {
  laptop_charger: '#f26419',
  mobile_charger: '#2d9c95',
  other: '#5f6caf',
}

const getApplianceColor = (id, index = 0) => {
  if (APPLIANCE_COLORS[id]) return APPLIANCE_COLORS[id]
  if (id.startsWith('laptop')) return ['#f26419', '#f2a541', '#d7263d', '#dc2626'][index % 4]
  if (id.startsWith('mobile')) return ['#2d9c95', '#0f766e', '#135d66'][index % 3]
  return PIE_COLORS[index % PIE_COLORS.length]
}

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
  if (!rows || rows.length === 0) return []
  
  let maxTs = 0
  rows.forEach((row) => {
    const ts = toEpoch(row.timestamp || row.received_at)
    if (ts > maxTs) maxTs = ts
  })

  const latestRows = rows.filter(r => toEpoch(r.timestamp || r.received_at) === maxTs)
  
  const latestPerAppliance = new Map()
  latestRows.forEach((row) => {
    const key = `${row.device_id}:${row.appliance_id}`
    latestPerAppliance.set(key, row)
  })

  return [...latestPerAppliance.values()]
    .map((row) => ({
      name: row.appliance_label || row.appliance_id,
      appliance_id: row.appliance_id,
      power_w: Number(row.power_w || 0),
      energy_kwh: Number(row.energy_kwh || 0),
    }))
    .sort((a, b) => b.power_w - a.power_w)
}

function buildApplianceTimeline(rows) {
  const byTimestamp = new Map()
  const allKnownIds = new Set(rows.map(r => r.appliance_id).filter(Boolean))

  rows.forEach((row) => {
    const ts = row.timestamp || row.received_at
    if (!ts) return
    const key = ts
    
    if (!byTimestamp.has(key)) {
      const init = { timestamp: ts, label: formatTime(ts) }
      for (const id of allKnownIds) init[id] = 0 // Zero-fill to prevent chart floating
      byTimestamp.set(key, init)
    }

    const entry = byTimestamp.get(key)
    const appId = row.appliance_id || 'unknown'
    entry[appId] = Number(row.power_w || 0)
  })
  
  return [...byTimestamp.values()].sort(
    (a, b) => toEpoch(a.timestamp) - toEpoch(b.timestamp),
  ).slice(-120)
}

function App() {
  const [meterReadings, setMeterReadings] = useState([])
  const [disaggregatedReadings, setDisaggregatedReadings] = useState([])
  const [selectedSite, setSelectedSite] = useState('all')
  const [excludedAppliances, setExcludedAppliances] = useState(new Set())
  const [selectedDevice, setSelectedDevice] = useState('')
  const [limit, setLimit] = useState(DEFAULT_WINDOW)
  const [connectionState, setConnectionState] = useState('connecting')
  const [isSyncing, setIsSyncing] = useState(true)
  const [errorText, setErrorText] = useState('')
  const [lastSyncedAt, setLastSyncedAt] = useState(null)
  const [nilmStatus, setNilmStatus] = useState(null)
  const reconnectTimerRef = useRef(null)

  const syncRecentData = useRef(async () => {})

  const fetchNilmStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/nilm/status`)
      if (res.ok) setNilmStatus(await res.json())
    } catch { /* ignore */ }
  }, [])

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
    fetchNilmStatus()
    const interval = setInterval(() => {
      syncRecentData.current()
    }, REFRESH_MS)
    const nilmInterval = setInterval(fetchNilmStatus, 5000)
    return () => { clearInterval(interval); clearInterval(nilmInterval) }
  }, [fetchNilmStatus])

  useEffect(() => {
    let isActive = true
    let socket

    const connect = () => {
      if (!isActive) return

      setConnectionState('connecting')
      socket = new WebSocket(WS_URL)

      socket.onopen = () => {
        setConnectionState('live')
      }

      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'disaggregation') {
            setDisaggregatedReadings((prev) => mergeRows(prev, [msg], disaggregationKey))
          } else {
            setMeterReadings((prev) => mergeRows(prev, [msg], readingKey))
          }
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
        if (!isActive) return
        setConnectionState('offline')
        reconnectTimerRef.current = setTimeout(connect, 2500)
      }
    }

    connect()

    return () => {
      isActive = false
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (socket && socket.readyState <= 1) socket.close()
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
    if (!selectedDevice) return []
    return meterReadings.filter((row) => row.device_id === selectedDevice).slice(-limit)
  }, [meterReadings, selectedDevice, limit])

  const filteredDisaggregation = useMemo(() => {
    if (!selectedDevice) return []
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

  const applianceTimeline = useMemo(
    () => buildApplianceTimeline(filteredDisaggregation),
    [filteredDisaggregation],
  )

  const latestReading = filteredReadings.at(-1)

  const applianceLive = useMemo(() => {
    const map = {}
    applianceTotals.forEach((a) => { map[a.appliance_id] = a })
    return map
  }, [applianceTotals])

  const alertItems = useMemo(() => {
    if (!latestReading) return []
    const alerts = []
    if (latestReading.power_w > 150)
      alerts.push('High aggregate draw detected — multiple devices may be active.')
    if (latestReading.power_factor !== null && latestReading.power_factor < 0.82)
      alerts.push('Low power factor observed, investigate inductive loads.')
    if (latestReading.frequency_hz && (latestReading.frequency_hz < 49.9 || latestReading.frequency_hz > 50.1))
      alerts.push('Grid frequency drift noticed outside preferred range.')
    const laptopPw = applianceLive.laptop_charger?.power_w || 0
    const mobilePw = applianceLive.mobile_charger?.power_w || 0
    if (laptopPw > 60)
      alerts.push(`Laptop charger drawing ${metricValue(laptopPw, 0)} W — high charging load.`)
    if (mobilePw > 0 && laptopPw > 0)
      alerts.push('Both chargers detected simultaneously.')
    return alerts
  }, [latestReading, applianceLive])

  const activeAppliances = useMemo(
    () => applianceTotals.filter((row) => row.power_w > 5).length,
    [applianceTotals],
  )

  const energyTotal = Number(latestReading?.energy_kwh || 0)

  const nilmMode = nilmStatus?.mode || 'unknown'
  const nilmBadgeLabel = nilmMode === 'ml' ? 'ML Model Active' : nilmMode === 'heuristic' ? 'Heuristic Mode' : 'NILM Loading'

  const streamStatusLabel =
    connectionState === 'live'
      ? 'WebSocket live'
      : connectionState === 'connecting'
        ? 'Connecting stream'
        : 'Stream reconnecting'

  const showEmptyState = !isSyncing && filteredReadings.length === 0
  const tableRows = useMemo(() => {
    if (filteredReadings.length > 0) return filteredReadings
    return meterReadings.slice(-Math.max(limit, 8))
  }, [filteredReadings, meterReadings, limit])

  const bufferPct = useMemo(() => {
    if (!nilmStatus?.buffers || !selectedDevice) return 0
    return nilmStatus.buffers[selectedDevice]?.fill_pct || 0
  }, [nilmStatus, selectedDevice])

  // --- What-if analysis ---
  const toggleAppliance = useCallback((appId) => {
    setExcludedAppliances((prev) => {
      const next = new Set(prev)
      if (next.has(appId)) {
        next.delete(appId)
      } else {
        next.add(appId)
      }
      return next
    })
  }, [])

  const whatIfData = useMemo(() => {
    const currentTotal = applianceTotals.reduce((s, a) => s + a.power_w, 0)
    const projectedTotal = applianceTotals
      .filter((a) => !excludedAppliances.has(a.appliance_id))
      .reduce((s, a) => s + a.power_w, 0)
    const savedW = currentTotal - projectedTotal
    const reductionPct = currentTotal > 0 ? (savedW / currentTotal) * 100 : 0
    // Rough cost estimate: ₹8 per kWh, extrapolate current draw over a month
    const monthlySaved = (savedW / 1000) * 24 * 30 * 8
    return { currentTotal, projectedTotal, savedW, reductionPct, monthlySaved }
  }, [applianceTotals, excludedAppliances])

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">NILM Smart Meter Control Room</p>
          <h1>Live Energy Disaggregation Dashboard</h1>
          <p className="subtext">
            Real-time appliance-level energy monitoring powered by deep learning (Seq2Point CNN).
          </p>
          <p className="backend-meta">
            API: <code>{API_BASE}</code>
          </p>
        </div>
        <div className="hero-badges">
          <div className="live-chip" role="status" aria-live="polite">
            <span className={`dot ${connectionState === 'live' ? 'on' : 'off'}`}></span>
            {connectionState === 'live' ? <Wifi size={14} /> : <WifiOff size={14} />}
            {streamStatusLabel}
          </div>
          <div className={`nilm-badge ${nilmMode}`}>
            <BrainCircuit size={14} />
            {nilmBadgeLabel}
          </div>
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
              if (firstDevice) setSelectedDevice(firstDevice.device_id)
            }}
          >
            <option value="all">All Sites</option>
            {sites.map((site) => (
              <option key={site} value={site}>{site}</option>
            ))}
          </select>
        </label>
        <label>
          Device
          <select value={selectedDevice} onChange={(e) => setSelectedDevice(e.target.value)}>
            {deviceOptions.map((device) => (
              <option key={device.device_id} value={device.device_id}>{device.device_id}</option>
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
        {bufferPct > 0 && bufferPct < 100 && (
          <span className="buffer-chip">Buffer: {bufferPct.toFixed(0)}%</span>
        )}
      </section>

      {/* KPI cards */}
      <section className="kpi-grid">
        <article className="panel kpi">
          <Zap size={18} />
          <h3>Aggregate Power</h3>
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

      {/* NILM Appliance Status Cards */}
      <section className="nilm-section">
        <h2 className="section-title"><BrainCircuit size={18} /> NILM Disaggregation</h2>
        <div className="appliance-cards">
          {applianceTotals.map((a, i) => {
            const id = a.appliance_id;
            const label = a.name;
            const pw = a.power_w;
            // Only consider it "ON" if drawing > 2W
            const isOn = pw > 2;
            const color = getApplianceColor(id, i);
            return (
              <article key={id} className={`panel appliance-card ${isOn ? 'appliance-on' : 'appliance-off'}`}>
                <div className="appliance-header">
                  <span className="appliance-name">{label}</span>
                  <span className={`appliance-status ${isOn ? 'on' : 'off'}`}>{isOn ? 'ON' : 'OFF'}</span>
                </div>
                <p className="appliance-power">{metricValue(pw, 1)} <span className="unit">W</span></p>
                <div className="appliance-bar">
                  <div
                    className="appliance-bar-fill"
                    style={{
                      width: `${Math.min((pw / Math.max(latestReading?.power_w || 1, 1)) * 100, 100)}%`,
                      backgroundColor: color,
                    }}
                  />
                </div>
              </article>
            )
          })}
        </div>
      </section>

      {/* Appliance power timeline */}
      {applianceTimeline.length > 0 && (
        <section className="panel chart-card">
          <h2>Appliance Power Timeline (NILM Output)</h2>
          <ResponsiveContainer width="100%" height={310}>
            <AreaChart data={applianceTimeline}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d7e5e8" />
              <XAxis dataKey="label" minTickGap={20} />
              <YAxis />
              <Tooltip />
              <Legend />
              {applianceTotals.map((a, i) => {
                 const id = a.appliance_id;
                 const color = getApplianceColor(id, i);
                 return (
                   <Area 
                     key={id} 
                     type="monotone" 
                     dataKey={id} 
                     stackId="1" 
                     fill={color} 
                     fillOpacity={0.5} 
                     stroke={color} 
                     strokeWidth={2} 
                     name={`${a.name} (W)`} 
                   />
                 )
              })}
            </AreaChart>
          </ResponsiveContainer>
        </section>
      )}

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
                   <Cell key={row.name} fill={getApplianceColor(row.appliance_id, index)} />
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
                   <Cell key={row.name} fill={getApplianceColor(row.appliance_id, index)} />
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
            NILM mode: <code>{nilmMode}</code> | Appliances: <code>{(nilmStatus?.appliances || []).join(', ') || 'N/A'}</code>
          </p>
        </article>
      </section>

      {/* What-If Load Analysis */}
      {applianceTotals.length > 0 && (
        <section className="panel whatif-section">
          <h2><Lightbulb size={18} /> What-If Load Analysis</h2>
          <p className="whatif-desc">Toggle appliances off to simulate load removal and see projected demand reduction.</p>
          <div className="whatif-grid">
            <div className="whatif-toggles">
              {applianceTotals.map((a) => {
                const isExcluded = excludedAppliances.has(a.appliance_id)
                return (
                  <div key={a.appliance_id} className={`whatif-row ${isExcluded ? 'excluded' : ''}`}>
                    <button
                      className="whatif-toggle"
                      onClick={() => toggleAppliance(a.appliance_id)}
                      aria-label={`Toggle ${a.name}`}
                    >
                      {isExcluded
                        ? <ToggleLeft size={22} className="toggle-icon off" />
                        : <ToggleRight size={22} className="toggle-icon on" />}
                    </button>
                    <span className="whatif-label">{a.name}</span>
                    <span className="whatif-pw">{metricValue(a.power_w, 1)} W</span>
                  </div>
                )
              })}
            </div>
            <div className="whatif-result">
              <div className="whatif-bars">
                <div className="whatif-bar-group">
                  <span className="whatif-bar-label">Current</span>
                  <div className="whatif-bar">
                    <div className="whatif-bar-fill current" style={{ width: '100%' }} />
                  </div>
                  <span className="whatif-bar-value">{metricValue(whatIfData.currentTotal, 0)} W</span>
                </div>
                <div className="whatif-bar-group">
                  <span className="whatif-bar-label">Projected</span>
                  <div className="whatif-bar">
                    <div
                      className="whatif-bar-fill projected"
                      style={{ width: `${whatIfData.currentTotal > 0 ? (whatIfData.projectedTotal / whatIfData.currentTotal) * 100 : 0}%` }}
                    />
                  </div>
                  <span className="whatif-bar-value">{metricValue(whatIfData.projectedTotal, 0)} W</span>
                </div>
              </div>
              {whatIfData.savedW > 0 ? (
                <div className="whatif-savings">
                  <p className="whatif-saving-line">🔻 <strong>{metricValue(whatIfData.savedW, 0)} W</strong> reduction ({metricValue(whatIfData.reductionPct, 1)}%)</p>
                  <p className="whatif-saving-cost">Estimated saving: ~₹{metricValue(whatIfData.monthlySaved, 0)}/month</p>
                </div>
              ) : (
                <p className="whatif-no-change">Toggle off appliances above to simulate load removal.</p>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  )
}

export default App
