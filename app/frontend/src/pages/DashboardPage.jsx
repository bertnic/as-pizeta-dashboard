import { useState, useEffect, useRef, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import {
  BarChart, Bar, Line, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend,
  ComposedChart,
} from "recharts"
import sbLogo from "../assets/logo.svg"

const DEFAULT_PROVS = []
const PROV_COLORS_BASE = { BG: "#00f5d4", BS: "#7b61ff", LC: "#ff6b6b", MB: "#ffd60a", SO: "#00b4d8" }
const PROV_COLORS_EXTRA = ["#c77dff", "#06d6a0", "#ff9f1c", "#2ec4b6", "#e71d36", "#ff006e", "#8338ec"]
function pickProvColor(code) {
  if (PROV_COLORS_BASE[code]) return PROV_COLORS_BASE[code]
  let h = 0
  for (let i = 0; i < code.length; i++) h = (h + code.charCodeAt(i)) % PROV_COLORS_EXTRA.length
  return PROV_COLORS_EXTRA[h]
}
const ACCENT = "#00f5d4"
/** Linea anno precedente nei grafici mensili (arancione). */
const CHART_PRIOR_YEAR_ORANGE = "#fb923c"
/** Riempimento sotto la curva anno precedente (dietro le barre). */
const CHART_PRIOR_YEAR_FILL_OPACITY = 0.22

/**
 * Target / % sotto il grafico: solo mesi già “trascorsi” nel calendario reale quando
 * l’anno del grafico è l’anno corrente (es. a marzo 2026 non mostrare Apr–Dic).
 */
/** Chip provincia: ONLINE sempre dopo le altre (ordine API invariato per il resto). */
function provincesOrderedWithOnlineLast(list) {
  if (!list?.length) return list || []
  const online = []
  const rest = []
  for (const p of list) {
    if (String(p).toUpperCase() === "ONLINE") online.push(p)
    else rest.push(p)
  }
  return [...rest, ...online]
}

function isTargetMonthElapsed(chartYear, monthIndex0) {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth()
  if (chartYear < y) return true
  if (chartYear > y) return false
  return monthIndex0 <= m
}

/** Long-press on a province chip → select all; short press → that province only. */
const PROV_LONG_PRESS_MS = 550

const PROV_FILTER_TITLE =
  "Clic / tocco breve: solo questa provincia. Tenere premuto: torna a tutte le province."

// ─── Helpers ──────────────────────────────────────────────────────────────────
function kpi(val, prefix = "€") {
  if (val >= 1000) return `${prefix}${(val / 1000).toFixed(1)}k`
  return `${prefix}${val.toFixed(0)}`
}

function truncateProductLabel(name, max = 40) {
  if (!name || name.length <= max) return name
  return `${name.slice(0, max - 1)}…`
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────
export default function DashboardPage({ user, setUser }) {
  /** Chart-ready payload from ``/api/datamart/summary`` (SQLite ``sales``). */
  const [mart, setMart] = useState(null)
  /** `null` = default year from API (newest with data). */
  const [selectedYear, setSelectedYear] = useState(null)
  const [dataLoading, setDataLoading] = useState(true)
  /** True when ``/api/datamart/summary`` risponde 401 (sessione assente / scaduta). */
  const [datamartUnauthorized, setDatamartUnauthorized] = useState(false)
  const [activeProvs, setActiveProvs] = useState([...DEFAULT_PROVS])
  const [selectedProducts, setSelectedProducts] = useState([])
  /** Union of product rows seen this year — search/Invio use this so filtering by DIKIROGEN does not drop ZIDOVAL from the picker. */
  const [pickerCatalog, setPickerCatalog] = useState([])
  const [productSearch, setProductSearch] = useState("")
  const [productListOpen, setProductListOpen] = useState(false)
  const [view, setView] = useState("overview") // overview | products
  const nav = useNavigate()

  const productFilterRef = useRef(null)
  const longPressTimerRef = useRef(null)
  const longPressConsumedRef = useRef(false)
  const provinceListRef = useRef([])
  const [provTitleDesktop, setProvTitleDesktop] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia("(hover: hover) and (pointer: fine)")
    const sync = () => setProvTitleDesktop(mq.matches)
    sync()
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", sync)
      return () => mq.removeEventListener("change", sync)
    }
    mq.addListener(sync)
    return () => mq.removeListener(sync)
  }, [])

  useEffect(() => {
    return () => {
      if (longPressTimerRef.current) {
        clearTimeout(longPressTimerRef.current)
        longPressTimerRef.current = null
      }
    }
  }, [])

  const clearProvLongPressTimer = () => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
  }

  const releaseProvCapture = (e) => {
    const el = e.currentTarget
    if (typeof el.releasePointerCapture === "function") {
      try {
        if (el.hasPointerCapture?.(e.pointerId)) el.releasePointerCapture(e.pointerId)
      } catch {
        /* already released */
      }
    }
  }

  const onProvPointerDown = (p) => (e) => {
    if (e.button != null && e.button !== 0) return
    longPressConsumedRef.current = false
    clearProvLongPressTimer()
    if (typeof e.currentTarget.setPointerCapture === "function") {
      try {
        e.currentTarget.setPointerCapture(e.pointerId)
      } catch {
        /* e.g. pointer not eligible */
      }
    }
    longPressTimerRef.current = window.setTimeout(() => {
      longPressTimerRef.current = null
      longPressConsumedRef.current = true
      const all = provinceListRef.current
      if (all?.length) setActiveProvs([...all])
    }, PROV_LONG_PRESS_MS)
  }

  const onProvPointerUp = (p) => (e) => {
    if (e.button != null && e.button !== 0) return
    clearProvLongPressTimer()
    releaseProvCapture(e)
    if (longPressConsumedRef.current) {
      longPressConsumedRef.current = false
      return
    }
    setActiveProvs([p])
  }

  const onProvPointerCancel = (e) => {
    clearProvLongPressTimer()
    longPressConsumedRef.current = false
    releaseProvCapture(e)
  }

  const productSelectionSignature = JSON.stringify([...selectedProducts].sort())

  useEffect(() => {
    const baseRaw = import.meta.env.BASE_URL || "/"
    const base = baseRaw.endsWith("/") ? baseRaw : `${baseRaw}/`
    const url = `${base}api/datamart/summary`
    const products = JSON.parse(productSelectionSignature)
    const ac = new AbortController()
    setDataLoading(true)

    const init = { credentials: "same-origin", cache: "no-store", signal: ac.signal }
    const params = new URLSearchParams()
    if (selectedYear != null) params.set("year", String(selectedYear))
    if (products.length > 0) params.set("products_json", JSON.stringify(products))
    const qs = params.toString()
    const getUrl = qs ? `${url}?${qs}` : url
    /** Prefer GET + ``products_json`` (works behind proxies that block POST or strip duplicate ``product=``). POST if query is huge. */
    const usePost = products.length > 0 && getUrl.length > 1900
    const req = usePost
      ? fetch(url, {
          ...init,
          method: "POST",
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            Accept: "application/json",
          },
          body: JSON.stringify({
            year: selectedYear ?? null,
            products,
          }),
        })
      : fetch(getUrl, { ...init, method: "GET" })

    req
      .then(async r => {
        if (r.status === 401) {
          return { __unauthorized: true }
        }
        if (!r.ok) return null
        return await r.json()
      })
      .then(martRes => {
        if (martRes && martRes.__unauthorized) {
          setMart(null)
          setDatamartUnauthorized(true)
          return
        }
        setDatamartUnauthorized(false)
        if (martRes == null || typeof martRes !== "object") {
          setMart(null)
          return
        }
        const byProvince =
          martRes.byProvince != null && typeof martRes.byProvince === "object"
            ? martRes.byProvince
            : {}
        setMart({ ...martRes, byProvince })
      })
      .catch(e => {
        if (e.name === "AbortError") return
        setMart(null)
      })
      .finally(() => {
        if (!ac.signal.aborted) setDataLoading(false)
      })

    return () => ac.abort()
  }, [selectedYear, productSelectionSignature])

  useEffect(() => {
    if (!mart) return
    const incoming =
      mart.productsCatalog?.length ? mart.productsCatalog
      : mart.topProducts?.length ? mart.topProducts
      : null
    if (!incoming?.length) return
    setPickerCatalog(prev => {
      const map = new Map(prev.map(r => [r.name, r]))
      for (const row of incoming) {
        map.set(row.name, row)
      }
      return [...map.values()].sort((a, b) => (b.rev || 0) - (a.rev || 0))
    })
  }, [mart])

  useEffect(() => {
    if (!productListOpen) return
    const onDown = (ev) => {
      if (productFilterRef.current && !productFilterRef.current.contains(ev.target)) {
        setProductListOpen(false)
      }
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [productListOpen])

  useEffect(() => {
    if (!productListOpen) return
    const onKey = (ev) => {
      if (ev.key === "Escape") setProductListOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [productListOpen])

  const chartReady = Boolean(
    mart && Array.isArray(mart.months) && mart.months.length > 0 && mart.byProvince != null,
  )
  const provinceList = mart?.provinces?.length ? mart.provinces : DEFAULT_PROVS
  const provinceListForChips = useMemo(
    () => provincesOrderedWithOnlineLast(provinceList),
    [provinceList],
  )
  /** Only reset chip selection when the API province set changes (not on every new `mart` object). */
  const provinceCodesKey = mart?.provinces?.length ? mart.provinces.join(",") : ""

  useEffect(() => {
    provinceListRef.current = provinceList
  }, [provinceList])

  useEffect(() => {
    if (mart?.provinces?.length) setActiveProvs([...mart.provinces])
    else setActiveProvs([...DEFAULT_PROVS])
  }, [provinceCodesKey])

  const logout = async () => {
    await fetch(import.meta.env.BASE_URL + "auth/logout", { method: "POST" })
    setUser(null); nav("/auth")
  }

  const months = mart?.months || []
  const byProv = mart?.byProvince || {}
  const topProds = mart?.topProducts || []
  const qnorm = productSearch.trim().toLowerCase()
  const productSuggestions = pickerCatalog
    .filter(row => !selectedProducts.includes(row.name))
    .filter(row => !qnorm || row.name.toLowerCase().includes(qnorm))
    .slice(0, 100)

  const addProductFilter = (name) => {
    if (!name) return
    setSelectedProducts(prev => (prev.includes(name) ? prev : [...prev, name]))
    setProductSearch("")
    setProductListOpen(false)
  }

  /** Invio: aggiunge tutti i prodotti il cui nome contiene la sottostringa cercata (es. "diki" → tutte le DIKIROGEN…). */
  const addAllProductsMatchingSearch = () => {
    const q = productSearch.trim().toLowerCase()
    if (!q) return
    const selected = new Set(selectedProducts)
    const out = [...selectedProducts]
    for (const row of pickerCatalog) {
      const name = row.name
      if (!name || !name.toLowerCase().includes(q) || selected.has(name)) continue
      selected.add(name)
      out.push(name)
    }
    if (out.length === selectedProducts.length) return
    setSelectedProducts(out)
    setProductSearch("")
    setProductListOpen(false)
  }

  const clearProductFilters = () => setSelectedProducts([])
  const priorBy = mart?.priorYear?.byProvince || {}
  const targetBy = mart?.target?.byProvince || {}
  const yearOptions = mart?.availableYears?.length ? mart.availableYears : mart?.year != null ? [mart.year] : []
  const chartYear = selectedYear ?? mart?.year ?? new Date().getFullYear()

  const monthlyData = months.map((m, i) => {
    const obj = { month: m, monthIndex: i }
    let totalQty = 0, totalRev = 0
    let priorTotalRev = 0, priorTotalQty = 0
    let targetTotalQty = 0
    activeProvs.forEach(p => {
      if (byProv[p]) {
        obj[`${p}_qty`] = byProv[p].qty[i] || 0
        obj[`${p}_rev`] = byProv[p].rev[i] || 0
        totalQty += byProv[p].qty[i] || 0
        totalRev += byProv[p].rev[i] || 0
      }
      if (priorBy[p]) {
        priorTotalRev += priorBy[p].rev[i] || 0
        priorTotalQty += priorBy[p].qty[i] || 0
      }
      if (targetBy[p]) {
        targetTotalQty += targetBy[p].qty[i] || 0
      }
    })
    obj.totalQty = totalQty
    obj.totalRev = totalRev
    obj.priorTotalRev = priorTotalRev
    obj.priorTotalQty = priorTotalQty
    obj.targetTotalQty = targetTotalQty
    const targetElapsed = mart?.target && isTargetMonthElapsed(chartYear, i)
    obj.targetLineQty =
      targetElapsed && targetTotalQty > 0 ? targetTotalQty : null
    return obj
  })

  const totalQty = monthlyData.reduce((s, r) => s + r.totalQty, 0)
  const totalRev = monthlyData.reduce((s, r) => s + r.totalRev, 0)
  /** Recharts can keep stale scales; remount when filter or totals change. */
  const provinceChipsKey = [...activeProvs].sort().join(",")
  const chartsRemountKey = `${productSelectionSignature}-${provinceChipsKey}-${totalRev.toFixed(4)}-${totalQty.toFixed(4)}`
  const totalPriorRev = monthlyData.reduce((s, r) => s + r.priorTotalRev, 0)
  const totalPriorQty = monthlyData.reduce((s, r) => s + r.priorTotalQty, 0)
  const totalTargetQty = monthlyData.reduce((s, r) => s + r.targetTotalQty, 0)
  const yoyRevPct =
    mart?.priorYear && totalPriorRev > 0
      ? ((totalRev - totalPriorRev) / totalPriorRev) * 100
      : null
  const yoyQtyPct =
    mart?.priorYear && totalPriorQty > 0
      ? ((totalQty - totalPriorQty) / totalPriorQty) * 100
      : null
  const vsTargetQtyPct =
    mart?.target && totalTargetQty > 0 ? (totalQty / totalTargetQty) * 100 : null
  const avgMonthRev = months.length ? totalRev / months.length : 0
  const bestMonth = [...monthlyData].sort((a, b) => b.totalRev - a.totalRev)[0]

  const pieData = Object.entries(byProv)
    .filter(([p]) => activeProvs.includes(p))
    .map(([p, v]) => ({
      name: p,
      value: v.rev.reduce((s, x) => s + (x || 0), 0),
      color: pickProvColor(p),
    }))

  const productFilterActive = selectedProducts.length > 0
  const productFilterChartSuffix = productFilterActive
    ? ` · ${selectedProducts.length} prodotti (filtro)`
    : ""

  const fmtEuro = (n) =>
    (Number(n) || 0).toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  /** Tooltip: solo totale mese anno corrente vs anno precedente (fatturato). */
  const fatturatoTotalsTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    const row = payload[0]?.payload
    if (!row) return null
    const curYear = mart?.year ?? ""
    return (
      <div className="tt">
        <p className="tt-label">{label}</p>
        <p style={{ color: ACCENT }}>
          {curYear}: €{fmtEuro(row.totalRev)}
        </p>
        {mart?.priorYear ? (
          <p style={{ color: "#94a3b8" }}>
            {mart.priorYear.year}: €{fmtEuro(row.priorTotalRev)}
          </p>
        ) : null}
      </div>
    )
  }

  /** Tooltip volumi: una riga TARGET vs VOLUME con valori; anno prec. sotto. */
  const volumeTotalsTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    const row = payload[0]?.payload
    if (!row) return null
    const mi = row.monthIndex ?? 0
    const showTarget = Boolean(mart?.target && isTargetMonthElapsed(chartYear, mi))
    const vol = Number(row.totalQty) || 0
    const tgt = showTarget ? Number(row.targetTotalQty) || 0 : 0
    const pct = showTarget && tgt > 0 ? (vol / tgt) * 100 : null
    return (
      <div className="tt">
        <p className="tt-label">{label}</p>
        {showTarget && tgt > 0 ? (
          <p
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "0.35rem",
              alignItems: "baseline",
              lineHeight: 1.45,
            }}
          >
            <span style={{ fontWeight: 700, color: "#8892a4" }}>TARGET vs VOLUME</span>
            <span style={{ color: "#7b61ff", fontWeight: 600 }}>
              {vol.toLocaleString("it-IT")} pz
            </span>
            <span style={{ color: "#5c6578" }}>/</span>
            <span style={{ color: "#fbbf24", fontWeight: 600 }}>
              {tgt.toLocaleString("it-IT")} pz
            </span>
            {pct != null ? (
              <span style={{ color: pct >= 100 ? "#06d6a0" : "#ff6b6b", fontWeight: 700 }}>
                ({pct.toFixed(0)}%)
              </span>
            ) : null}
          </p>
        ) : (
          <p style={{ color: "#7b61ff", fontWeight: 600, lineHeight: 1.45 }}>
            VOLUME: {vol.toLocaleString("it-IT")} pz
          </p>
        )}
        {mart?.priorYear ? (
          <p style={{ color: "#94a3b8", marginTop: "0.2rem" }}>
            {mart.priorYear.year}: {(Number(row.priorTotalQty) || 0).toLocaleString("it-IT")} pz
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <div className="dash">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sb-logo">
          <img className="sb-logo-img" src={sbLogo} alt="Pizeta logo" />
        </div>

        <nav className="sb-nav">
          {[["overview", "Overview", "◈"], ["products", "Prodotti", "▦"]].map(([v, l, ic]) => (
            <button key={v} className={`sb-item ${view === v ? "active" : ""}`} onClick={() => setView(v)}>
              <span className="sb-icon">{ic}</span>{l}
            </button>
          ))}
        </nav>

        <div className="sb-datasets">
          <p className="sb-section-label">Dati</p>
          {dataLoading && (
            <div className="ds-item"><span className="ds-name">Caricamento…</span></div>
          )}
          {!dataLoading && chartReady && (
            <div className="ds-item active">
              <span className="ds-dot" style={{ background: ACCENT }} />
              <span className="ds-name">Dataset vendite</span>
            </div>
          )}
          {!dataLoading && !chartReady && (
            <div className="ds-item"><span className="ds-name text-muted">Nessun dato mart</span></div>
          )}
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
            <h1 className="dash-title">{view === "overview" ? "Vendite Anna Sedran" : "Analisi Prodotti"}</h1>
            <p className="dash-sub">
              {dataLoading
                ? "Caricamento…"
                : datamartUnauthorized
                    ? "Sessione scaduta o non autorizzato — rifai il login"
                    : !chartReady
                      ? "Database senza vendite IMS — importa ETL o collega SQLite"
                      : null}
            </p>
          </div>
          <div className="dash-header-right">
            <div className="dash-header-controls">
              {yearOptions.length > 0 && (
                <label className="year-select-wrap">
                  <span className="year-select-label">Anno</span>
                  <select
                    className="year-select"
                    value={selectedYear ?? mart?.year ?? ""}
                    onChange={(e) => {
                      setSelectedProducts([])
                      setPickerCatalog([])
                      setSelectedYear(Number(e.target.value))
                    }}
                    disabled={dataLoading}
                  >
                    {yearOptions.map((y) => (
                      <option key={y} value={y}>{y}</option>
                    ))}
                  </select>
                </label>
              )}
              <div className="prov-filters">
                {provinceListForChips.map(p => (
                  <button
                    key={p}
                    type="button"
                    className={`prov-btn ${activeProvs.includes(p) ? "active" : ""}`}
                    style={activeProvs.includes(p) ? { borderColor: pickProvColor(p), color: pickProvColor(p) } : {}}
                    title={provTitleDesktop ? PROV_FILTER_TITLE : undefined}
                    onPointerDown={onProvPointerDown(p)}
                    onPointerUp={onProvPointerUp(p)}
                    onPointerCancel={onProvPointerCancel}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
            {pickerCatalog.length > 0 && (
              <div className="product-filter" ref={productFilterRef}>
                <span className="product-filter-label">Prodotti</span>
                <div className="product-filter-body">
                  <div className="product-search-wrap">
                    <input
                      type="search"
                      className="product-search-input"
                      placeholder="Cerca per nome…"
                      value={productSearch}
                      onChange={(e) => {
                        setProductSearch(e.target.value)
                        setProductListOpen(true)
                      }}
                      onClick={() => setProductListOpen(true)}
                      onFocus={() => setProductListOpen(true)}
                      onKeyDown={(e) => {
                        if (e.key !== "Enter") return
                        e.preventDefault()
                        addAllProductsMatchingSearch()
                      }}
                      aria-expanded={productListOpen}
                      aria-haspopup="listbox"
                      autoComplete="off"
                    />
                    {productListOpen && (
                      <ul className="product-search-dropdown" role="listbox">
                        {productSuggestions.length === 0 ? (
                          <li className="product-search-empty" role="presentation">Nessun risultato</li>
                        ) : (
                          productSuggestions.map(row => (
                            <li key={row.name} role="option">
                              <button
                                type="button"
                                className="product-search-option"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => addProductFilter(row.name)}
                              >
                                {row.name}
                              </button>
                            </li>
                          ))
                        )}
                      </ul>
                    )}
                  </div>
                  <div className="product-pills-row">
                    {selectedProducts.map(name => (
                      <span key={name} className="product-pill">
                        <span className="product-pill-text" title={name}>{truncateProductLabel(name)}</span>
                        <button
                          type="button"
                          className="product-pill-remove"
                          aria-label={`Rimuovi ${name}`}
                          onClick={() => setSelectedProducts(prev => prev.filter(x => x !== name))}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                    {selectedProducts.length > 0 && (
                      <button type="button" className="product-filter-clear" onClick={clearProductFilters}>
                        Tutti i prodotti
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </header>

        {view === "overview" && !chartReady && !dataLoading && (
          <div className="chart-card" style={{ marginTop: "1.5rem", padding: "2rem" }}>
            <h3 className="chart-title">Nessun dataset nel database</h3>
            {datamartUnauthorized ? (
              <p style={{ color: "#fbbf24", lineHeight: 1.6 }}>
                Risposta <strong>401</strong> da <code style={{ color: "#cbd5e1" }}>/api/datamart/summary</code>: sessione non valida.
                Esci e rifai il login, oppure ricarica la pagina.
              </p>
            ) : (
              <div style={{ color: "#8892a4", lineHeight: 1.65 }}>
                <p style={{ margin: "0 0 0.85rem" }}>
                  Il backend apre <strong>solo</strong> <code style={{ color: "#cbd5e1" }}>DATA_DIR/pizeta.sqlite</code> (utenti + mart).
                  Opzionale: <code style={{ color: "#cbd5e1" }}>etl_build_db.py</code> in{" "}
                  <code style={{ color: "#cbd5e1" }}>apps/dashboard/data/</code> usa lo stesso <code style={{ color: "#cbd5e1" }}>DATA_DIR</code> e
                  il workbook <code style={{ color: "#cbd5e1" }}>mono/datalake.xlsx</code> (o <code style={{ color: "#cbd5e1" }}>datalake/DATABASE.xlsx</code>).
                </p>
                <p style={{ margin: "0 0 0.85rem" }}>
                  Se nel file già ci sono vendite ma vedi questo messaggio, quasi sempre <code style={{ color: "#cbd5e1" }}>DATA_DIR</code> non
                  punta alla cartella giusta (fuori da <code style={{ color: "#cbd5e1" }}>mono/</code> il default è{" "}
                  <code style={{ color: "#cbd5e1" }}>/data</code>). Imposta{" "}
                  <code style={{ color: "#cbd5e1" }}>DATA_DIR</code> sulla directory che contiene{" "}
                  <code style={{ color: "#cbd5e1" }}>pizeta.sqlite</code> (es. <code style={{ color: "#cbd5e1" }}>mono/var</code>). Da{" "}
                  <code style={{ color: "#cbd5e1" }}>app/backend/</code>:{" "}
                  <code style={{ color: "#cbd5e1" }}>python dev_db_status.py</code> mostra il path effettivo e i conteggi righe.
                </p>
                <p style={{ margin: 0 }}>
                  Dev Vite: Flask su porta <strong>8080</strong> con prefisso <code style={{ color: "#cbd5e1" }}>/pizeta/dashboard</code>.
                  In Network, se <code style={{ color: "#cbd5e1" }}>api/datamart/summary</code> è 404 o non JSON, il proxy non
                  raggiunge il backend giusto.
                </p>
              </div>
            )}
          </div>
        )}

        {view === "overview" && chartReady && !dataLoading && (
          <>
            {productFilterActive && (
              <div
                className={`filter-active-banner${mart?.filteredEmpty ? " filter-active-banner--warn" : ""}`}
                role="status"
              >
                {mart?.filteredEmpty
                  ? "Nessuna vendita in questo anno per i prodotti selezionati (nomi diversi da SQLite o anno senza dati). Svuota il filtro o scegli altri SKU dal catalogo."
                  : `KPI e grafici sotto riflettono solo i prodotti selezionati (${selectedProducts.length}).`}
              </div>
            )}
            {/* KPI row */}
            <div className="kpi-row">
              {[
                {
                  label: "Fatturato Totale",
                  val: `€${totalRev.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                  sub: productFilterActive ? `${selectedProducts.length} prodotti` : "periodo selezionato",
                  color: ACCENT,
                },
                ...(mart?.priorYear && yoyRevPct != null
                  ? [{
                      label: `vs ${mart.priorYear.year} (fatt.)`,
                      val: `${yoyRevPct >= 0 ? "+" : ""}${yoyRevPct.toFixed(1)}%`,
                      sub: `€${totalPriorRev.toLocaleString("it-IT", { maximumFractionDigits: 0 })} anno prec.`,
                      color: yoyRevPct >= 0 ? "#06d6a0" : "#ff6b6b",
                    }]
                  : []),
                { label: "Unità Vendute", val: totalQty.toLocaleString("it-IT"), sub: "pezzi totali", color: "#7b61ff" },
                ...(mart?.priorYear && yoyQtyPct != null
                  ? [{
                      label: `vs ${mart.priorYear.year} (pezzi)`,
                      val: `${yoyQtyPct >= 0 ? "+" : ""}${yoyQtyPct.toFixed(1)}%`,
                      sub: `${totalPriorQty.toLocaleString("it-IT")} anno prec.`,
                      color: "#8892a4",
                    }]
                  : []),
                ...(mart?.target && vsTargetQtyPct != null
                  ? [{
                      label: "vs target (pezzi)",
                      val: `${vsTargetQtyPct.toFixed(1)}%`,
                      sub: `${totalTargetQty.toLocaleString("it-IT")} target`,
                      color: "#fbbf24",
                    }]
                  : []),
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
                <h3 className="chart-title">
                  Fatturato Mensile per Provincia
                  {mart?.priorYear ? (
                    <>
                      {" - "}
                      <span style={{ color: CHART_PRIOR_YEAR_ORANGE, fontWeight: 700 }}>
                        {mart.priorYear.year}
                      </span>
                    </>
                  ) : null}
                </h3>
                <ResponsiveContainer key={chartsRemountKey} width="100%" height={260}>
                  <ComposedChart
                    data={monthlyData}
                    margin={{ top: 5, right: 10, left: 0, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                    <XAxis dataKey="month" tick={{ fill: "#6b7a99", fontSize: 12 }} interval={0} />
                    <YAxis tick={{ fill: "#6b7a99", fontSize: 11 }} tickFormatter={v => `€${(v / 1000).toFixed(0)}k`} />
                    <Tooltip content={fatturatoTotalsTooltip} />
                    {mart?.priorYear ? (
                      <Area
                        type="monotone"
                        dataKey="priorTotalRev"
                        name={`Tot. fatt. ${mart.priorYear.year}`}
                        stroke="none"
                        fill={CHART_PRIOR_YEAR_ORANGE}
                        fillOpacity={CHART_PRIOR_YEAR_FILL_OPACITY}
                        isAnimationActive={false}
                      />
                    ) : null}
                    {activeProvs.map(p => (
                      <Bar key={p} dataKey={`${p}_rev`} name={p} stackId="a"
                        fill={pickProvColor(p)} radius={[0, 0, 0, 0]} />
                    ))}
                    {mart?.priorYear ? (
                      <Line
                        type="monotone"
                        dataKey="priorTotalRev"
                        name={`Tot. fatt. ${mart.priorYear.year}`}
                        stroke={CHART_PRIOR_YEAR_ORANGE}
                        strokeWidth={2}
                        strokeDasharray="6 4"
                        dot={false}
                      />
                    ) : null}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              <div className="chart-card">
                <h3 className="chart-title">Quota Fatturato per Provincia</h3>
                <ResponsiveContainer key={`${chartsRemountKey}-pie`} width="100%" height={260}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={95}
                      dataKey="value" nameKey="name" paddingAngle={3}>
                      {pieData.map((e, i) => (
                        <Cell key={i} fill={e.color || "#444"} stroke="none" />
                      ))}
                    </Pie>
                    <Legend formatter={(v) => <span style={{ color: "#8892a4" }}>{v}</span>} />
                    <Tooltip formatter={(v) => `€${v.toLocaleString("it-IT", { minimumFractionDigits: 2 })}`} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Volume: barre anno corrente (per provincia), linee anno prec. + target */}
            <div className="chart-card" style={{ marginTop: "1.2rem" }}>
              <h3 className="chart-title">
                Volumi Mensili (unità)
                {mart?.target ? (
                  <>
                    {" - "}
                    <span style={{ color: "#fbbf24", fontWeight: 700 }}>TARGET</span>
                  </>
                ) : null}
                {mart?.priorYear ? (
                  <>
                    {" - "}
                    <span style={{ color: CHART_PRIOR_YEAR_ORANGE, fontWeight: 700 }}>
                      {mart.priorYear.year}
                    </span>
                  </>
                ) : null}
              </h3>
              <ResponsiveContainer key={`${chartsRemountKey}-vol`} width="100%" height={260}>
                <ComposedChart
                  data={monthlyData}
                  margin={{ top: 5, right: 10, left: 4, bottom: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                  <XAxis
                    dataKey="month"
                    tick={{ fill: "#6b7a99", fontSize: 12 }}
                    interval={0}
                  />
                  <YAxis tick={{ fill: "#6b7a99", fontSize: 11 }} />
                  <Tooltip content={volumeTotalsTooltip} />
                  {mart?.priorYear ? (
                    <Area
                      type="monotone"
                      dataKey="priorTotalQty"
                      name={`Tot. pezzi ${mart.priorYear.year}`}
                      stroke="none"
                      fill={CHART_PRIOR_YEAR_ORANGE}
                      fillOpacity={CHART_PRIOR_YEAR_FILL_OPACITY}
                      isAnimationActive={false}
                    />
                  ) : null}
                  {activeProvs.map(p => (
                    <Bar
                      key={p}
                      dataKey={`${p}_qty`}
                      name={p}
                      stackId="vol"
                      fill={pickProvColor(p)}
                      radius={[0, 0, 0, 0]}
                    />
                  ))}
                  {mart?.priorYear ? (
                    <Line
                      type="monotone"
                      dataKey="priorTotalQty"
                      name={`Tot. pezzi ${mart.priorYear.year}`}
                      stroke={CHART_PRIOR_YEAR_ORANGE}
                      strokeWidth={2}
                      strokeDasharray="6 4"
                      dot={false}
                    />
                  ) : null}
                  {mart?.target ? (
                    <Line
                      type="monotone"
                      dataKey="targetLineQty"
                      name={`Target pezzi ${mart.target.year}`}
                      stroke="#fbbf24"
                      strokeWidth={2}
                      strokeDasharray="4 4"
                      dot={false}
                      connectNulls={false}
                    />
                  ) : null}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </>
        )}

        {view === "products" && !chartReady && !dataLoading && (
          <div className="chart-card" style={{ marginTop: "1.5rem", padding: "2rem" }}>
            <h3 className="chart-title">Nessun dato prodotti</h3>
            <p style={{ color: "#8892a4" }}>Nessun mart in SQLite.</p>
          </div>
        )}

        {view === "products" && chartReady && !dataLoading && (
          <>
            {productFilterActive && (
              <div
                className={`filter-active-banner${mart?.filteredEmpty ? " filter-active-banner--warn" : ""}`}
                role="status"
              >
                {mart?.filteredEmpty
                  ? "Nessun dato per i prodotti selezionati in questo anno."
                  : `Grafici e tabella: solo i prodotti selezionati (${selectedProducts.length}).`}
              </div>
            )}
            <div className="charts-row" style={{ marginTop: "1rem" }}>
              <div className="chart-card wide">
                <h3 className="chart-title">Top Prodotti – Fatturato{productFilterChartSuffix}</h3>
                <ResponsiveContainer key={`${chartsRemountKey}-tp-rev`} width="100%" height={300}>
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
                <h3 className="chart-title">Top Prodotti – Unità{productFilterChartSuffix}</h3>
                <ResponsiveContainer key={`${chartsRemountKey}-tp-qty`} width="100%" height={300}>
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
              <h3 className="chart-title">Dettaglio Prodotti{productFilterChartSuffix}</h3>
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

      </main>
    </div>
  )
}
