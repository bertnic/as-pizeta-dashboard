import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend
} from "recharts"

// ─── Raw embedded data from PDF ───────────────────────────────────────────────
const EMBEDDED = {
  label: "Anno 2025 (Jan–Oct) – Dati iniziali",
  provinces: ["BG", "BS", "LC", "MB", "SO"],
  months: ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott"],
  byProvince: {
    BG: { qty: [73, 73, 101, 153, 77, 72, 72, 40, 116, 137], rev: [1222.47, 985.54, 1485.6, 2401.95, 1246.91, 1189.45, 1126.99, 635.61, 1780.12, 2249.77] },
    BS: { qty: [26, 22, 25, 56, 20, 14, 9, 37, 72, 56], rev: [380.38, 287.99, 358.71, 890.77, 303.62, 202.97, 138.39, 565.82, 1072.29, 851.06] },
    LC: { qty: [18, 17, 20, 14, 21, 129, 26, 15, 34, 49], rev: [282.89, 297.19, 322.8, 200.35, 316.36, 2417.13, 412.58, 238.13, 514.29, 717.58] },
    MB: { qty: [110, 110, 82, 76, 90, 98, 104, 53, 105, 128], rev: [1736.89, 1792.86, 1313.47, 1296.97, 1535.61, 1719.36, 1760.32, 902.17, 1727.88, 2151.35] },
    SO: { qty: [9, 8, 5, 8, 10, 3, 1, 6, 10, 7], rev: [152.77, 152.59, 100.55, 161.76, 140.73, 35.85, 20.1, 86.73, 133.07, 119.76] },
  },
  topProducts: [
    { name: "DIKIROGEN ZERO BUSTINE", qty: 306, rev: 6161.88 },
    { name: "ISIDE FEMME OVULI", qty: 73, rev: 734.47 },
    { name: "ENDOMOX 600", qty: 61, rev: 887.36 },
    { name: "NAXEND", qty: 158, rev: 2348.21 },
    { name: "ZIDOVAL GEL", qty: 110, rev: 1533.4 },
    { name: "ISIDE HPV OVULI", qty: 42, rev: 660.47 },
    { name: "PROBENAT GZ BUSTE", qty: 24, rev: 374.27 },
    { name: "STAMINFLUX FAST COMPR", qty: 22, rev: 263.47 },
    { name: "ISIDE", qty: 34, rev: 388.28 },
    { name: "FLAVOXELLE CAPS", qty: 8, rev: 133.83 },
  ]
}

const PROV_COLORS = { BG: "#00f5d4", BS: "#7b61ff", LC: "#ff6b6b", MB: "#ffd60a", SO: "#00b4d8" }
const ACCENT = "#00f5d4"

// ─── Helpers ──────────────────────────────────────────────────────────────────
function kpi(val, prefix = "€") {
  if (val >= 1000) return `${prefix}${(val / 1000).toFixed(1)}k`
  return `${prefix}${val.toFixed(0)}`
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="tt">
      <p className="tt-label">{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }}>
          {p.name}: {typeof p.value === "number" ? p.value.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : p.value}
        </p>
      ))}
    </div>
  )
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────
export default function DashboardPage({ user, setUser }) {
  const [datasets, setDatasets] = useState([EMBEDDED])
  const [activeDS, setActiveDS] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState("")
  const [activeProvs, setActiveProvs] = useState(["BG", "BS", "LC", "MB", "SO"])
  const [view, setView] = useState("overview") // overview | products | map
  const nav = useNavigate()

  // Load server uploads
  useEffect(() => {
    fetch(import.meta.env.BASE_URL + "api/data").then(r => r.json()).then(d => {
      if (d.uploads?.length) {
        setDatasets(prev => [...prev, ...d.uploads.map(u => ({ label: u.label, raw: u.rows }))])
      }
    }).catch(() => { })
  }, [])

  const logout = async () => {
    await fetch(import.meta.env.BASE_URL + "auth/logout", { method: "POST" })
    setUser(null); nav("/auth")
  }

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]; if (!file) return
    const fd = new FormData()
    fd.append("file", file)
    fd.append("label", file.name.replace(".pdf", ""))
    setUploading(true); setUploadMsg("")
    const r = await fetch(import.meta.env.BASE_URL + "api/upload", { method: "POST", body: fd })
    const d = await r.json()
    setUploading(false)
    if (d.ok) {
      setUploadMsg(`✓ Caricato: ${d.label} (${d.rows} righe)`)
      fetch(import.meta.env.BASE_URL + "api/data").then(r => r.json()).then(dd => {
        if (dd.uploads?.length) setDatasets([EMBEDDED, ...dd.uploads.map(u => ({ label: u.label, raw: u.rows }))])
      })
    } else setUploadMsg("⚠ Errore caricamento")
  }

  const ds = datasets[activeDS]

  // Build monthly totals for current dataset
  const months = ds.months || EMBEDDED.months
  const byProv = ds.byProvince || EMBEDDED.byProvince
  const topProds = ds.topProducts || EMBEDDED.topProducts

  const monthlyData = months.map((m, i) => {
    const obj = { month: m }
    let totalQty = 0, totalRev = 0
    activeProvs.forEach(p => {
      if (byProv[p]) {
        obj[`${p}_qty`] = byProv[p].qty[i] || 0
        obj[`${p}_rev`] = byProv[p].rev[i] || 0
        totalQty += byProv[p].qty[i] || 0
        totalRev += byProv[p].rev[i] || 0
      }
    })
    obj.totalQty = totalQty; obj.totalRev = totalRev
    return obj
  })

  const totalQty = monthlyData.reduce((s, r) => s + r.totalQty, 0)
  const totalRev = monthlyData.reduce((s, r) => s + r.totalRev, 0)
  const avgMonthRev = totalRev / months.length
  const bestMonth = [...monthlyData].sort((a, b) => b.totalRev - a.totalRev)[0]

  const pieData = Object.entries(byProv)
    .filter(([p]) => activeProvs.includes(p))
    .map(([p, v]) => ({ name: p, value: v.rev.reduce((s, x) => s + (x || 0), 0) }))

  const toggleProv = (p) => setActiveProvs(prev =>
    prev.includes(p) ? (prev.length > 1 ? prev.filter(x => x !== p) : prev) : [...prev, p]
  )

  return (
    <div className="dash">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sb-logo">
          <span className="logo-icon">⬡</span>
          <span>Pharma<strong>Analytics</strong></span>
        </div>

        <nav className="sb-nav">
          {[["overview", "Overview", "◈"], ["products", "Prodotti", "▦"], ["upload", "Carica PDF", "⊕"]].map(([v, l, ic]) => (
            <button key={v} className={`sb-item ${view === v ? "active" : ""}`} onClick={() => setView(v)}>
              <span className="sb-icon">{ic}</span>{l}
            </button>
          ))}
        </nav>

        <div className="sb-datasets">
          <p className="sb-section-label">Dataset</p>
          {datasets.map((d, i) => (
            <button key={i} className={`ds-item ${activeDS === i ? "active" : ""}`} onClick={() => setActiveDS(i)}>
              <span className="ds-dot" style={{ background: i === 0 ? ACCENT : "#7b61ff" }} />
              <span className="ds-name">{d.label}</span>
            </button>
          ))}
        </div>

        <div className="sb-bottom">
          <div className="sb-user">
            {user.picture && <img src={user.picture} className="avatar" alt="" />}
            <span className="sb-uname">{user.name || user.email}</span>
          </div>
          <button className="btn-logout" onClick={logout}>Esci</button>
        </div>
      </aside>

      {/* Main */}
      <main className="main-content">
        {/* Header */}
        <header className="dash-header">
          <div>
            <h1 className="dash-title">{view === "overview" ? "Panoramica Vendite" : view === "products" ? "Analisi Prodotti" : "Carica Dati"}</h1>
            <p className="dash-sub">{ds.label}</p>
          </div>
          <div className="prov-filters">
            {["BG", "BS", "LC", "MB", "SO"].map(p => (
              <button key={p} className={`prov-btn ${activeProvs.includes(p) ? "active" : ""}`}
                style={activeProvs.includes(p) ? { borderColor: PROV_COLORS[p], color: PROV_COLORS[p] } : {}}
                onClick={() => toggleProv(p)}>{p}</button>
            ))}
          </div>
        </header>

        {view === "overview" && (
          <>
            {/* KPI row */}
            <div className="kpi-row">
              {[
                { label: "Fatturato Totale", val: `€${totalRev.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, sub: "periodo selezionato", color: ACCENT },
                { label: "Unità Vendute", val: totalQty.toLocaleString("it-IT"), sub: "pezzi totali", color: "#7b61ff" },
                { label: "Media Mensile", val: kpi(avgMonthRev), sub: "€/mese", color: "#ffd60a" },
                { label: "Mese Top", val: bestMonth?.month || "—", sub: `€${bestMonth?.totalRev?.toFixed(0) || 0}`, color: "#ff6b6b" },
              ].map((k, i) => (
                <div className="kpi-card" key={i} style={{ "--accent": k.color }}>
                  <p className="kpi-label">{k.label}</p>
                  <p className="kpi-val">{k.val}</p>
                  <p className="kpi-sub">{k.sub}</p>
                </div>
              ))}
            </div>

            {/* Charts row */}
            <div className="charts-row">
              <div className="chart-card wide">
                <h3 className="chart-title">Fatturato Mensile per Provincia</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={monthlyData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                    <XAxis dataKey="month" tick={{ fill: "#6b7a99", fontSize: 12 }} />
                    <YAxis tick={{ fill: "#6b7a99", fontSize: 11 }} tickFormatter={v => `€${(v / 1000).toFixed(0)}k`} />
                    <Tooltip content={<CustomTooltip />} />
                    {activeProvs.map(p => (
                      <Bar key={p} dataKey={`${p}_rev`} name={p} stackId="a"
                        fill={PROV_COLORS[p]} radius={[0, 0, 0, 0]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="chart-card">
                <h3 className="chart-title">Quota Fatturato per Provincia</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={95}
                      dataKey="value" nameKey="name" paddingAngle={3}>
                      {pieData.map((e, i) => (
                        <Cell key={i} fill={PROV_COLORS[e.name] || "#444"} stroke="none" />
                      ))}
                    </Pie>
                    <Legend formatter={(v) => <span style={{ color: "#8892a4" }}>{v}</span>} />
                    <Tooltip formatter={(v) => `€${v.toLocaleString("it-IT", { minimumFractionDigits: 2 })}`} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Volume line chart */}
            <div className="chart-card" style={{ marginTop: "1.2rem" }}>
              <h3 className="chart-title">Volumi Mensili (unità)</h3>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={monthlyData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                  <XAxis dataKey="month" tick={{ fill: "#6b7a99", fontSize: 12 }} />
                  <YAxis tick={{ fill: "#6b7a99", fontSize: 11 }} />
                  <Tooltip content={<CustomTooltip />} />
                  {activeProvs.map(p => (
                    <Line key={p} type="monotone" dataKey={`${p}_qty`} name={p}
                      stroke={PROV_COLORS[p]} strokeWidth={2} dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        )}

        {view === "products" && (
          <>
            <div className="charts-row" style={{ marginTop: "1rem" }}>
              <div className="chart-card wide">
                <h3 className="chart-title">Top Prodotti – Fatturato</h3>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={topProds} layout="vertical" margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" horizontal={false} />
                    <XAxis type="number" tick={{ fill: "#6b7a99", fontSize: 11 }} tickFormatter={v => `€${v}`} />
                    <YAxis dataKey="name" type="category" width={160} tick={{ fill: "#8892a4", fontSize: 11 }} />
                    <Tooltip formatter={v => `€${v.toFixed(2)}`} />
                    <Bar dataKey="rev" name="Fatturato" fill={ACCENT} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="chart-card">
                <h3 className="chart-title">Top Prodotti – Unità</h3>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={topProds} layout="vertical" margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" horizontal={false} />
                    <XAxis type="number" tick={{ fill: "#6b7a99", fontSize: 11 }} />
                    <YAxis dataKey="name" type="category" width={160} tick={{ fill: "#8892a4", fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="qty" name="Unità" fill="#7b61ff" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Products table */}
            <div className="table-card" style={{ marginTop: "1.2rem" }}>
              <h3 className="chart-title">Dettaglio Prodotti</h3>
              <table className="data-table">
                <thead>
                  <tr><th>Prodotto</th><th>Unità</th><th>Fatturato</th><th>Prezzo medio</th></tr>
                </thead>
                <tbody>
                  {[...topProds].sort((a, b) => b.rev - a.rev).map((p, i) => (
                    <tr key={i}>
                      <td className="prod-name">{p.name}</td>
                      <td>{p.qty}</td>
                      <td>€{p.rev.toLocaleString("it-IT", { minimumFractionDigits: 2 })}</td>
                      <td>€{p.qty > 0 ? (p.rev / p.qty).toFixed(2) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {view === "upload" && (
          <div className="upload-area">
            <div className="upload-card">
              <div className="upload-icon">⊕</div>
              <h2>Carica Nuovo Report PDF</h2>
              <p>Carica un PDF nel formato QIMS mensile per aggiungere nuovi dati alla dashboard.</p>
              <label className="btn-upload-label">
                <input type="file" accept=".pdf" onChange={handleUpload} style={{ display: "none" }} />
                {uploading ? <span className="spinner-sm" /> : "Seleziona PDF"}
              </label>
              {uploadMsg && <p className={`upload-msg ${uploadMsg.startsWith("✓") ? "ok" : "err"}`}>{uploadMsg}</p>}
            </div>
            <div className="upload-info">
              <h3>Dataset caricati</h3>
              {datasets.map((d, i) => (
                <div key={i} className="ds-row">
                  <span className="ds-dot-lg" style={{ background: i === 0 ? ACCENT : "#7b61ff" }} />
                  <span>{d.label}</span>
                  {i === 0 && <span className="ds-badge">predefinito</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
