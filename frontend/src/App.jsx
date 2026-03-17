import { useEffect, useMemo, useState } from 'react'
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
import { Activity, Gauge, PlugZap, ShieldCheck, TriangleAlert, Zap } from 'lucide-react'
import { appendLiveTick, generateMockDataset } from './mockData'
import './App.css'

const PIE_COLORS = ['#0f766e', '#0ea5e9', '#f59e0b', '#ef4444', '#7c3aed', '#14b8a6']

function formatTime(value) {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function latestByDevice(readings, deviceId) {
  const filtered = readings.filter((row) => row.device_id === deviceId)
  return filtered.at(-1)
}

function buildApplianceTotals(rows, deviceId) {
  const aggregate = new Map()
  rows
    .filter((row) => row.device_id === deviceId)
    .forEach((row) => {
      const key = row.appliance_label || row.appliance_id
      const current = aggregate.get(key) || 0
      aggregate.set(key, current + row.power_w)
    })

  return [...aggregate.entries()]
    .map(([name, power]) => ({ name, power_w: Number(power.toFixed(2)) }))
    .sort((a, b) => b.power_w - a.power_w)
}

function App() {
  const [dataset, setDataset] = useState(() => generateMockDataset(90))
  const [selectedSite, setSelectedSite] = useState('all')
  const [selectedDevice, setSelectedDevice] = useState('esp32-a1')
  const [limit, setLimit] = useState(60)
  const [isLive, setIsLive] = useState(true)

  useEffect(() => {
    if (!isLive) {
      return undefined
    }

    const timer = setInterval(() => {
      setDataset((previous) => appendLiveTick(previous))
    }, 3000)

    return () => clearInterval(timer)
  }, [isLive])

  const deviceOptions = useMemo(
    () => dataset.devices.filter((d) => selectedSite === 'all' || d.site_id === selectedSite),
    [dataset.devices, selectedSite],
  )

  const filteredReadings = useMemo(
    () => dataset.meterReadings.filter((row) => row.device_id === selectedDevice).slice(-limit),
    [dataset.meterReadings, selectedDevice, limit],
  )

  const filteredDisaggregation = useMemo(
    () => dataset.disaggregatedReadings.filter((row) => row.device_id === selectedDevice).slice(-limit * 6),
    [dataset.disaggregatedReadings, selectedDevice, limit],
  )

  const chartSeries = useMemo(
    () =>
      filteredReadings.map((row) => ({
        ...row,
        label: formatTime(row.timestamp),
      })),
    [filteredReadings],
  )

  const applianceTotals = useMemo(
    () => buildApplianceTotals(filteredDisaggregation, selectedDevice),
    [filteredDisaggregation, selectedDevice],
  )

  const latestReading = useMemo(
    () => latestByDevice(dataset.meterReadings, selectedDevice),
    [dataset.meterReadings, selectedDevice],
  )

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

  const energyToday = useMemo(
    () =>
      Number(
        filteredReadings
          .slice(-1)
          .map((r) => r.energy_kwh)[0]
          ?.toFixed(3) || 0,
      ),
    [filteredReadings],
  )

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">NILM Smart Meter Control Room</p>
          <h1>Real-Time Energy Intelligence Dashboard</h1>
          <p className="subtext">
            Live mock stream modeled on your ingestion API payloads for frontend demo and stakeholder presentation.
          </p>
        </div>
        <div className="live-chip" role="status" aria-live="polite">
          <span className={`dot ${isLive ? 'on' : 'off'}`}></span>
          {isLive ? 'Live feed enabled' : 'Live feed paused'}
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
              const firstDevice = dataset.devices.find(
                (d) => nextSite === 'all' || d.site_id === nextSite,
              )
              if (firstDevice) {
                setSelectedDevice(firstDevice.device_id)
              }
            }}
          >
            <option value="all">All Sites</option>
            {dataset.sites.map((site) => (
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
        <button className="live-btn" onClick={() => setIsLive((v) => !v)}>
          {isLive ? 'Pause Stream' : 'Resume Stream'}
        </button>
      </section>

      <section className="kpi-grid">
        <article className="panel kpi">
          <Zap size={18} />
          <h3>Instant Power</h3>
          <p>{latestReading?.power_w?.toFixed(0) || 0} W</p>
        </article>
        <article className="panel kpi">
          <PlugZap size={18} />
          <h3>Energy (kWh)</h3>
          <p>{energyToday}</p>
        </article>
        <article className="panel kpi">
          <Gauge size={18} />
          <h3>Power Factor</h3>
          <p>{latestReading?.power_factor?.toFixed(2) || '0.00'}</p>
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
              <CartesianGrid strokeDasharray="3 3" stroke="#dbe6e5" />
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
                  <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.5} />
                  <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#dbe6e5" />
              <XAxis dataKey="label" minTickGap={20} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Area type="monotone" dataKey="energy_kwh" fill="url(#energy)" stroke="#f59e0b" strokeWidth={2} name="Energy (kWh)" />
              <Line type="monotone" dataKey="voltage_v" stroke="#7c3aed" strokeWidth={2} dot={false} name="Voltage (V)" />
            </AreaChart>
          </ResponsiveContainer>
        </article>
      </section>

      <section className="grid-2">
        <article className="panel chart-card">
          <h2>Appliance Consumption Mix</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={applianceTotals.slice(0, 6)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#dbe6e5" />
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
                  <th>Time</th>
                  <th>Power (W)</th>
                  <th>Voltage (V)</th>
                  <th>Current (A)</th>
                  <th>PF</th>
                </tr>
              </thead>
              <tbody>
                {filteredReadings.slice(-8).reverse().map((row) => (
                  <tr key={`${row.device_id}-${row.timestamp}`}>
                    <td>{formatTime(row.timestamp)}</td>
                    <td>{row.power_w.toFixed(0)}</td>
                    <td>{row.voltage_v.toFixed(1)}</td>
                    <td>{row.current_a.toFixed(2)}</td>
                    <td>{row.power_factor.toFixed(2)}</td>
                  </tr>
                ))}
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
            Model source: <code>/api/v1/readings</code> and <code>/api/v1/disaggregation</code> schema-compatible mock stream.
          </p>
        </article>
      </section>
    </div>
  )
}

export default App
