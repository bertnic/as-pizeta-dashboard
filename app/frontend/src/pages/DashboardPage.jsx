import { useState, useEffect, useRef, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import {
  BarChart, Bar, Line, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend, Scatter,
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
  const [metricMode, setMetricMode] = useState("qty") // qty | rev
  /** Union of product rows seen this year — search/Invio use this so filtering by DIKIROGEN does not drop ZIDOVAL from the picker. */
  const [pickerCatalog, setPickerCatalog] = useState([])
  const [productSearch, setProductSearch] = useState("")
  const [productListOpen, setProductListOpen] = useState(false)
  const [view, setView] = useState("overview") // overview | products
  const [selectedProductMonth, setSelectedProductMonth] = useState(0) // 0 = all
  /** Vista prodotti: ordina per metrica (fatt./pezzi) o per performance vs target. */
  const [productsSortMode, setProductsSortMode] = useState("metric") // metric | target
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

  const effectiveSelectedProducts = view === "overview" ? selectedProducts : []
  const productSelectionSignature = JSON.stringify([...selectedProducts].sort())
  const effectiveProductSelectionSignature = JSON.stringify([...effectiveSelectedProducts].sort())

  useEffect(() => {
    const baseRaw = import.meta.env.BASE_URL || "/"
    const base = baseRaw.endsWith("/") ? baseRaw : `${baseRaw}/`
    const url = `${base}api/datamart/summary`
    const products = JSON.parse(effectiveProductSelectionSignature)
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
  }, [selectedYear, effectiveProductSelectionSignature])

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
  const productsSeries = mart?.productsSeries || []
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

  const sortProductsByRevThenZeros = (rows) =>
    [...rows].sort((a, b) => {
      const ar = Number(a.rev) || 0
      const br = Number(b.rev) || 0
      const aZero = ar === 0
      const bZero = br === 0
      if (aZero !== bZero) return aZero ? 1 : -1
      if (aZero && bZero) return String(a.name).localeCompare(String(b.name), "it")
      return br - ar
    })

  const sortProductsByQtyThenZeros = (rows) =>
    [...rows].sort((a, b) => {
      const aq = Number(a.qty) || 0
      const bq = Number(b.qty) || 0
      const aZero = aq === 0
      const bZero = bq === 0
      if (aZero !== bZero) return aZero ? 1 : -1
      if (aZero && bZero) return String(a.name).localeCompare(String(b.name), "it")
      return bq - aq
    })

  /** Rapporto qty/target (unico dato target API): migliore sopra, senza target in fondo. */
  const sortProductsByTargetVs = (rows) =>
    [...rows].sort((a, b) => {
      const ta = Number(a.targetQty) || 0
      const tb = Number(b.targetQty) || 0
      const qa = Number(a.qty) || 0
      const qb = Number(b.qty) || 0
      const ra = ta > 0 ? qa / ta : -1
      const rb = tb > 0 ? qb / tb : -1
      if (ra < 0 && rb < 0) return String(a.name).localeCompare(String(b.name), "it")
      if (ra < 0) return 1
      if (rb < 0) return -1
      return rb - ra
    })

  const productsRowsMerged = useMemo(() => {
    const baseSource =
      mart?.productsCatalog?.length ? mart.productsCatalog
      : topProds
    const baseNames = [...new Set(baseSource.map((r) => r.name).filter(Boolean))]
    const baseByName = new Map(baseSource.map((r) => [r.name, r]))

    if (!productsSeries.length) {
      if (selectedProductMonth > 0) return []
      return baseNames.map((name) => {
        const row = baseByName.get(name)
        return {
          name,
          qty: Number(row?.qty) || 0,
          rev: Number(row?.rev) || 0,
          targetQty: 0,
        }
      })
    }

    const m = new Map()
    for (const r of productsSeries) {
      if (!r?.name) continue
      if (!activeProvs.includes(r.prov)) continue
      if (selectedProductMonth > 0 && r.month !== selectedProductMonth) continue
      const cur = m.get(r.name) || { name: r.name, qty: 0, rev: 0, targetQty: 0 }
      cur.qty += Number(r.qty) || 0
      cur.rev += Number(r.rev) || 0
      cur.targetQty += Number(r.targetQty) || 0
      m.set(r.name, cur)
    }

    const extraNames = [...m.keys()].filter((n) => !baseNames.includes(n))
    const orderedNames = [...baseNames, ...extraNames]
    return orderedNames.map((name) =>
      m.get(name) || { name, qty: 0, rev: 0, targetQty: 0 },
    )
  }, [mart?.productsCatalog, productsSeries, topProds, activeProvs, selectedProductMonth])

  const productsRows = useMemo(() => {
    const sorted =
      productsSortMode === "target"
        ? sortProductsByTargetVs(productsRowsMerged)
        : metricMode === "rev"
          ? sortProductsByRevThenZeros(productsRowsMerged)
          : sortProductsByQtyThenZeros(productsRowsMerged)
    return sorted.map((r) => ({
      ...r,
      targetRevImplied:
        Number(r.qty) > 0 && Number(r.targetQty) > 0
          ? (Number(r.rev) / Number(r.qty)) * Number(r.targetQty)
          : 0,
    }))
  }, [productsRowsMerged, productsSortMode, metricMode])
  const productsChartKey = `${metricMode}-${productsSortMode}-${selectedProductMonth}-${[...activeProvs].sort().join(",")}-${productsRows
    .map((r) => `${r.name}:${Number(r.rev || 0).toFixed(2)}`)
    .join("|")}`

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
  const elapsedMonthIndexes = months
    .map((_, i) => i)
    .filter((i) => isTargetMonthElapsed(chartYear, i))
  const totalRevElapsed = elapsedMonthIndexes.reduce((s, i) => s + (monthlyData[i]?.totalRev || 0), 0)
  const totalQtyElapsed = elapsedMonthIndexes.reduce((s, i) => s + (monthlyData[i]?.totalQty || 0), 0)
  const totalPriorRevElapsed = elapsedMonthIndexes.reduce((s, i) => s + (monthlyData[i]?.priorTotalRev || 0), 0)
  const totalPriorQtyElapsed = elapsedMonthIndexes.reduce((s, i) => s + (monthlyData[i]?.priorTotalQty || 0), 0)
  const totalTargetQtyElapsed = elapsedMonthIndexes.reduce((s, i) => s + (monthlyData[i]?.targetTotalQty || 0), 0)
  /** Con filtro prodotto: il target va confrontato ai mesi in cui c’è stata almeno una vendita (nel periodo trascorso), non a tutti i mesi del calendario con budget (altrimenti mar/apr con 0 vendite ma con target “assorbono” il %). */
  const totalTargetQtyElapsedInSalesMonths = elapsedMonthIndexes
    .filter((i) => (monthlyData[i]?.totalQty || 0) > 0)
    .reduce((s, i) => s + (monthlyData[i]?.targetTotalQty || 0), 0)
  const yoyRevPct =
    mart?.priorYear && totalPriorRevElapsed > 0
      ? ((totalRevElapsed - totalPriorRevElapsed) / totalPriorRevElapsed) * 100
      : null
  const yoyQtyPct =
    mart?.priorYear && totalPriorQtyElapsed > 0
      ? ((totalQtyElapsed - totalPriorQtyElapsed) / totalPriorQtyElapsed) * 100
      : null
  const vsTargetQtyPct = (() => {
    if (!mart?.target) return null
    if (selectedProducts.length > 0) {
      if (totalTargetQtyElapsedInSalesMonths <= 0) return null
      return (totalQtyElapsed / totalTargetQtyElapsedInSalesMonths) * 100
    }
    if (totalTargetQtyElapsed <= 0) return null
    return (totalQtyElapsed / totalTargetQtyElapsed) * 100
  })()
  const priorRevByMonth = months.map((_, i) => monthlyData[i]?.priorTotalRev || 0)
  const priorQtyByMonth = months.map((_, i) => monthlyData[i]?.priorTotalQty || 0)
  const projectionStartIdx = elapsedMonthIndexes.length
  const projectedRemainingRev = months
    .map((_, i) => i)
    .filter((i) => i >= projectionStartIdx)
    .reduce((s, i) => {
      const from = Math.max(0, i - 2)
      const windowVals = priorRevByMonth.slice(from, i + 1).filter((x) => x > 0)
      if (!windowVals.length) return s
      const movingAvg = windowVals.reduce((a, b) => a + b, 0) / windowVals.length
      return s + movingAvg
    }, 0)
  const projectedRemainingQty = months
    .map((_, i) => i)
    .filter((i) => i >= projectionStartIdx)
    .reduce((s, i) => {
      const from = Math.max(0, i - 2)
      const windowVals = priorQtyByMonth.slice(from, i + 1).filter((x) => x > 0)
      if (!windowVals.length) return s
      const movingAvg = windowVals.reduce((a, b) => a + b, 0) / windowVals.length
      return s + movingAvg
    }, 0)
  const estimatedYearEndRev = totalRevElapsed + projectedRemainingRev
  const estimatedYearEndQty = totalQtyElapsed + projectedRemainingQty
  /** Media sui soli mesi con attività (>0), non su 12 mesi fissi — altrimenti un prodotto con vendite solo in 2 mesi risultava ~totale/12. */
  const monthsWithRev = monthlyData.filter((r) => (Number(r.totalRev) || 0) > 0).length
  const monthsWithQty = monthlyData.filter((r) => (Number(r.totalQty) || 0) > 0).length
  const avgMonthRev = monthsWithRev > 0 ? totalRev / monthsWithRev : 0
  const avgMonthQty = monthsWithQty > 0 ? totalQty / monthsWithQty : 0
  const bestMonthRev = [...monthlyData].sort((a, b) => b.totalRev - a.totalRev)[0]
  const bestMonthQty = [...monthlyData].sort((a, b) => b.totalQty - a.totalQty)[0]

  const pieData = Object.entries(byProv)
    .filter(([p]) => activeProvs.includes(p))
    .map(([p, v]) => ({
      name: p,
      value:
        metricMode === "qty"
          ? v.qty.reduce((s, x) => s + (x || 0), 0)
          : v.rev.reduce((s, x) => s + (x || 0), 0),
      color: pickProvColor(p),
    }))
  const allProvincesSelected =
    provinceList.length > 0 &&
    activeProvs.length === provinceList.length &&
    provinceList.every((p) => activeProvs.includes(p))
  const singleProvinceSelected = activeProvs.length === 1
  const selectedProvinceCode = singleProvinceSelected ? activeProvs[0] : null
  const selectedProvinceQty = selectedProvinceCode
    ? (byProv[selectedProvinceCode]?.qty || []).reduce((s, x) => s + (x || 0), 0)
    : 0
  const selectedProvinceRev = selectedProvinceCode
    ? (byProv[selectedProvinceCode]?.rev || []).reduce((s, x) => s + (x || 0), 0)
    : 0
  const selectedProvinceTargetQtyFromSeries = selectedProvinceCode
    ? productsSeries.reduce((s, r) => {
        if (!r || r.prov !== selectedProvinceCode) return s
        const monthIndex0 = Number(r.month || 0) - 1
        if (monthIndex0 < 0 || !isTargetMonthElapsed(chartYear, monthIndex0)) return s
        return s + (Number(r.targetQty) || 0)
      }, 0)
    : 0
  const selectedProvinceTargetQtyFallback = selectedProvinceCode
    ? (targetBy[selectedProvinceCode]?.qty || []).reduce(
        (s, x, i) => s + (isTargetMonthElapsed(chartYear, i) ? (x || 0) : 0),
        0,
      )
    : 0
  const selectedProvinceTargetQty =
    selectedProvinceTargetQtyFromSeries > 0
      ? selectedProvinceTargetQtyFromSeries
      : selectedProvinceTargetQtyFallback
  const showProvincePie = allProvincesSelected
  const showProvinceTargetPie =
    metricMode === "qty" && singleProvinceSelected && selectedProvinceTargetQty > 0
  const hasSidePieChart = showProvincePie || showProvinceTargetPie
  const allProvinceOverTarget =
    metricMode === "qty" && Boolean(mart?.target) && totalTargetQty > 0 && totalQty >= totalTargetQty
  const isOverTarget = selectedProvinceQty > selectedProvinceTargetQty
  const targetDeltaQty = isOverTarget
    ? selectedProvinceQty - selectedProvinceTargetQty
    : selectedProvinceTargetQty - selectedProvinceQty
  const provinceTargetPieData = showProvinceTargetPie
    ? isOverTarget
      ? [
          { name: "Target budget", value: selectedProvinceTargetQty, color: "#fbbf24" },
          { name: "Pezzi oltre budget", value: targetDeltaQty, color: "#06d6a0" },
        ]
      : [
          { name: "Pezzi", value: selectedProvinceQty, color: "#7b61ff" },
          { name: "Mancano al budget", value: targetDeltaQty, color: "#fbbf24" },
        ]
    : []

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
            <h1 className="dash-title">{view === "overview" ? "Dashboard Anna Sedran" : "Analisi Prodotti"}</h1>
            <p className="dash-sub">
              {dataLoading
                ? "Caricamento…"
                : datamartUnauthorized
                    ? "Sessione scaduta o non autorizzato — rifai il login"
                    : !chartReady
                      ? "Database senza vendite IMS — importa ETL o collega SQLite"
                      : null}
            </p>
            <div className="mobile-view-switch" role="tablist" aria-label="Sezioni dashboard">
              {[["overview", "Overview"], ["products", "Prodotti"]].map(([v, l]) => (
                <button
                  key={v}
                  type="button"
                  role="tab"
                  aria-selected={view === v}
                  className={`mobile-view-btn ${view === v ? "active" : ""}`}
                  onClick={() => setView(v)}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>
          <div className="dash-header-right">
            <div className="dash-header-controls">
              {yearOptions.length > 0 && (
                <div className="year-metric-row">
                  <label className="year-select-wrap">
                    <span className="year-select-label">Anno</span>
                    <select
                      className="year-select"
                      value={selectedYear ?? mart?.year ?? ""}
                      onChange={(e) => {
                        setSelectedProducts([])
                        setPickerCatalog([])
                        setSelectedYear(Number(e.target.value))
                        setSelectedProductMonth(0)
                      }}
                      disabled={dataLoading}
                    >
                      {yearOptions.map((y) => (
                        <option key={y} value={y}>{y}</option>
                      ))}
                    </select>
                  </label>
                  <div className="seg-control" role="group" aria-label="Metrica grafici">
                    <button
                      type="button"
                      className={`prov-btn ${metricMode === "rev" ? "active" : ""}`}
                      onClick={() => setMetricMode("rev")}
                    >
                      Fatturato
                    </button>
                    <button
                      type="button"
                      className={`prov-btn ${metricMode === "qty" ? "active" : ""}`}
                      onClick={() => setMetricMode("qty")}
                    >
                      Pezzi
                    </button>
                  </div>
                </div>
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
              {view === "products" && (
                <label className="year-select-wrap">
                  <span className="year-select-label">Mese</span>
                  <select
                    className="year-select"
                    value={selectedProductMonth}
                    onChange={(e) => setSelectedProductMonth(Number(e.target.value))}
                    disabled={dataLoading}
                  >
                    <option value={0}>Tutti</option>
                    {months.map((m, i) => (
                      <option key={m} value={i + 1}>{m}</option>
                    ))}
                  </select>
                </label>
              )}
            </div>
            {view === "overview" && pickerCatalog.length > 0 && (
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
                  il workbook <code style={{ color: "#cbd5e1" }}>datalake/DATABASE.xlsx</code>.
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
                ...(metricMode === "rev"
                  ? [
                      {
                        label: "Fatturato Totale",
                        val: `€${totalRevElapsed.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                        sub: productFilterActive ? `${selectedProducts.length} prodotti · mesi attuali` : "mesi attuali",
                        color: ACCENT,
                      },
                      {
                        label: "Stima Fine Anno (fatt.)",
                        val: `€${estimatedYearEndRev.toLocaleString("it-IT", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`,
                        sub: mart?.priorYear
                          ? `media mobile su ${mart.priorYear.year}`
                          : "senza storico",
                        color: "#22d3ee",
                      },
                      ...(mart?.priorYear && yoyRevPct != null
                        ? [{
                            label: `vs ${mart.priorYear.year} (fatt.)`,
                            val: `${yoyRevPct >= 0 ? "+" : ""}${yoyRevPct.toFixed(1)}%`,
                            sub: `€${totalPriorRevElapsed.toLocaleString("it-IT", { maximumFractionDigits: 0 })} mesi analoghi`,
                            color: yoyRevPct >= 0 ? "#06d6a0" : "#ff6b6b",
                          }]
                        : []),
                    ]
                  : [
                      {
                        label: "Pezzi totali",
                        val: totalQtyElapsed.toLocaleString("it-IT"),
                        sub: productFilterActive ? `${selectedProducts.length} prodotti · mesi attuali` : "mesi attuali",
                        color: "#7b61ff",
                      },
                      {
                        label: "Stima Fine Anno (pezzi)",
                        val: estimatedYearEndQty.toLocaleString("it-IT", { maximumFractionDigits: 0 }),
                        sub: mart?.priorYear
                          ? `media mobile su ${mart.priorYear.year}`
                          : "senza storico",
                        color: "#22d3ee",
                      },
                      ...(mart?.priorYear && yoyQtyPct != null
                        ? [{
                            label: `vs ${mart.priorYear.year} (pezzi)`,
                            val: `${yoyQtyPct >= 0 ? "+" : ""}${yoyQtyPct.toFixed(1)}%`,
                            sub: `${totalPriorQtyElapsed.toLocaleString("it-IT")} pz mesi analoghi`,
                            color: yoyQtyPct >= 0 ? "#06d6a0" : "#ff6b6b",
                          }]
                        : []),
                      ...(mart?.target && vsTargetQtyPct != null
                        ? [{
                            label: "vs target (pezzi)",
                            val: `${vsTargetQtyPct.toFixed(1)}%`,
                            sub:
                              selectedProducts.length > 0
                                ? `${totalTargetQtyElapsedInSalesMonths.toLocaleString("it-IT")} target (mesi con vendite)`
                                : `${totalTargetQtyElapsed.toLocaleString("it-IT")} target mesi attuali`,
                            color: "#fbbf24",
                          }]
                        : []),
                    ]),
                {
                  label: "Media Mensile",
                  val:
                    metricMode === "rev"
                      ? kpi(avgMonthRev)
                      : Math.round(avgMonthQty).toLocaleString("it-IT"),
                  sub:
                    metricMode === "rev"
                      ? "€/mese · solo mesi con fatturato"
                      : "pz/mese · solo mesi con vendite",
                  color: "#ffd60a",
                },
                {
                  label: "Mese Top",
                  val: (metricMode === "rev" ? bestMonthRev : bestMonthQty)?.month || "—",
                  sub:
                    metricMode === "rev"
                      ? `€${(bestMonthRev?.totalRev ?? 0).toFixed(0)}`
                      : `${(bestMonthQty?.totalQty ?? 0).toLocaleString("it-IT")} pz`,
                  color: "#ff6b6b",
                },
              ].map((k, i) => (
                <div className="kpi-card" key={i} style={{ "--accent": k.color }}>
                  <p className="kpi-label">{k.label}</p>
                  <p className="kpi-val">{k.val}</p>
                  <p className="kpi-sub">{k.sub}</p>
                </div>
              ))}
            </div>

            {/* Charts row: solo volumi + pie condizionale */}
            <div className={`charts-row ${hasSidePieChart ? "" : "charts-row--single"}`.trim()}>
              <div className="chart-card wide">
                <h3 className="chart-title">
                  {metricMode === "qty" ? "Volumi Mensili (unità)" : "Fatturato Mensile per Provincia"}
                  {metricMode === "qty" && mart?.target ? (
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
                <ResponsiveContainer key={chartsRemountKey} width="100%" height={260}>
                  <ComposedChart
                    data={monthlyData}
                    margin={{ top: 5, right: 10, left: 0, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                    <XAxis dataKey="month" tick={{ fill: "#6b7a99", fontSize: 12 }} interval={0} />
                    <YAxis
                      tick={{ fill: "#6b7a99", fontSize: 11 }}
                      tickFormatter={metricMode === "rev" ? (v) => `€${(v / 1000).toFixed(0)}k` : undefined}
                    />
                    <Tooltip content={metricMode === "rev" ? fatturatoTotalsTooltip : volumeTotalsTooltip} />
                    {mart?.priorYear ? (
                      <Area
                        type="monotone"
                        dataKey={metricMode === "rev" ? "priorTotalRev" : "priorTotalQty"}
                        name={metricMode === "rev" ? `Tot. fatt. ${mart.priorYear.year}` : `Tot. pezzi ${mart.priorYear.year}`}
                        stroke="none"
                        fill={CHART_PRIOR_YEAR_ORANGE}
                        fillOpacity={CHART_PRIOR_YEAR_FILL_OPACITY}
                        isAnimationActive={false}
                      />
                    ) : null}
                    {activeProvs.map(p => (
                      <Bar key={p} dataKey={metricMode === "rev" ? `${p}_rev` : `${p}_qty`} name={p} stackId="vol"
                        fill={pickProvColor(p)} radius={[0, 0, 0, 0]} />
                    ))}
                    {mart?.priorYear ? (
                      <Line
                        type="monotone"
                        dataKey={metricMode === "rev" ? "priorTotalRev" : "priorTotalQty"}
                        name={metricMode === "rev" ? `Tot. fatt. ${mart.priorYear.year}` : `Tot. pezzi ${mart.priorYear.year}`}
                        stroke={CHART_PRIOR_YEAR_ORANGE}
                        strokeWidth={2}
                        strokeDasharray="6 4"
                        dot={false}
                      />
                    ) : null}
                    {metricMode === "qty" && mart?.target ? (
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

              {showProvincePie && (
                <div className="chart-card">
                  <h3 className="chart-title">
                    {metricMode === "qty" ? "Quota Pezzi per Provincia" : "Quota Fatturato per Provincia"}
                  </h3>
                  <div style={{ position: "relative" }}>
                    <ResponsiveContainer key={`${chartsRemountKey}-pie-province`} width="100%" height={260}>
                      <PieChart>
                        <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={95}
                          dataKey="value" nameKey="name" paddingAngle={3}>
                          {pieData.map((e, i) => (
                            <Cell key={i} fill={e.color || "#444"} stroke="none" />
                          ))}
                        </Pie>
                        <Legend formatter={(v) => <span style={{ color: "#8892a4" }}>{v}</span>} />
                        <Tooltip
                          formatter={(v) =>
                            metricMode === "qty"
                              ? `${Number(v || 0).toLocaleString("it-IT")} pz`
                              : `€${v.toLocaleString("it-IT", { minimumFractionDigits: 2 })}`
                          }
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div
                      aria-hidden="true"
                      style={{
                        position: "absolute",
                        left: "50%",
                        top: "50%",
                        transform: "translate(-50%, -58%)",
                        pointerEvents: "none",
                      }}
                    >
                      <span
                        className={`material-symbols-outlined pie-mood-icon${
                          allProvinceOverTarget ? " pie-mood-icon--over" : ""
                        }`}
                      >
                        {allProvinceOverTarget ? "mood" : "sentiment_neutral"}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {showProvinceTargetPie && (
                <div className="chart-card">
                  <h3 className="chart-title">
                    Pezzi vs Target {selectedProvinceCode ? `(${selectedProvinceCode})` : ""}
                  </h3>
                  <p className="kpi-sub" style={{ marginTop: "-0.25rem", marginBottom: "0.65rem" }}>
                    Pezzi: {selectedProvinceQty.toLocaleString("it-IT")} · Fatturato: €
                    {selectedProvinceRev.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </p>
                  <div style={{ position: "relative" }}>
                    <ResponsiveContainer key={`${chartsRemountKey}-pie-target`} width="100%" height={260}>
                      <PieChart>
                        <Pie
                          data={provinceTargetPieData}
                          cx="50%"
                          cy="50%"
                          innerRadius={60}
                          outerRadius={95}
                          dataKey="value"
                          nameKey="name"
                          paddingAngle={3}
                        >
                          {provinceTargetPieData.map((e, i) => (
                            <Cell key={i} fill={e.color || "#444"} stroke="none" />
                          ))}
                        </Pie>
                        <Legend formatter={(v) => <span style={{ color: "#8892a4" }}>{v}</span>} />
                        <Tooltip formatter={(v) => `${Number(v || 0).toLocaleString("it-IT")} pz`} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div
                      aria-hidden="true"
                      style={{
                        position: "absolute",
                        left: "50%",
                        top: "50%",
                        transform: "translate(-50%, -58%)",
                        pointerEvents: "none",
                      }}
                    >
                      <span
                        className={`material-symbols-outlined pie-mood-icon${isOverTarget ? " pie-mood-icon--over" : ""}`}
                      >
                        {isOverTarget ? "mood" : "sentiment_neutral"}
                      </span>
                    </div>
                  </div>
                  <p
                    className="kpi-sub"
                    style={{
                      marginTop: "0.35rem",
                      color: isOverTarget ? "#06d6a0" : "#fbbf24",
                      fontWeight: 600,
                    }}
                  >
                    {isOverTarget
                      ? `Superato budget di ${targetDeltaQty.toLocaleString("it-IT")} pezzi`
                      : `Mancano ${targetDeltaQty.toLocaleString("it-IT")} pezzi al budget`}
                  </p>
                </div>
              )}
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
            {productsRowsMerged.length === 0 ? (
              <div className="chart-card" style={{ marginTop: "1rem", padding: "1.4rem" }}>
                <h3 className="chart-title chart-title-row">
                  <span className="chart-title-prefix">PRODOTTI TOP</span>
                  <span className="chart-title-sep" aria-hidden>—</span>
                  <button
                    type="button"
                    className={`chart-sort-btn ${productsSortMode === "metric" ? "active" : ""}`}
                    onClick={() => setProductsSortMode("metric")}
                  >
                    {metricMode === "rev" ? "FATTURATO" : "PEZZI"}
                  </button>
                  <span className="chart-title-sep" aria-hidden>—</span>
                  <button
                    type="button"
                    className={`chart-sort-btn ${productsSortMode === "target" ? "active" : ""}`}
                    onClick={() => setProductsSortMode("target")}
                  >
                    TARGET
                  </button>
                </h3>
                <p style={{ color: "#8892a4" }}>
                  Nessun dato prodotti per i filtri correnti (mese/provincia).
                </p>
              </div>
            ) : (
              <div className="chart-card" style={{ marginTop: "1rem" }}>
                <h3 className="chart-title chart-title-row">
                  <span className="chart-title-prefix">PRODOTTI TOP</span>
                  <span className="chart-title-sep" aria-hidden>—</span>
                  <button
                    type="button"
                    className={`chart-sort-btn ${productsSortMode === "metric" ? "active" : ""}`}
                    onClick={() => setProductsSortMode("metric")}
                  >
                    {metricMode === "rev" ? "FATTURATO" : "PEZZI"}
                  </button>
                  <span className="chart-title-sep" aria-hidden>—</span>
                  <button
                    type="button"
                    className={`chart-sort-btn ${productsSortMode === "target" ? "active" : ""}`}
                    onClick={() => setProductsSortMode("target")}
                  >
                    TARGET
                  </button>
                </h3>
                <ResponsiveContainer width="100%" height={Math.max(320, 28 * productsRows.length + 60)}>
                  <ComposedChart
                    key={productsChartKey}
                    data={productsRows}
                    layout="vertical"
                    margin={{ top: 6, right: 26, left: 10, bottom: 6 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fill: "#6b7a99", fontSize: 11 }}
                      tickFormatter={metricMode === "rev" ? (v) => `€${(v / 1000).toFixed(0)}k` : undefined}
                    />
                    <YAxis dataKey="name" type="category" width={220} tick={{ fill: "#8892a4", fontSize: 11 }} />
                    <Tooltip
                      formatter={(v, name, item) => {
                        const key = item?.dataKey
                        const isTarget = key === "targetQty" || key === "targetRevImplied"
                        if (isTarget) {
                          return metricMode === "rev"
                            ? `€${Number(v || 0).toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} target (stim.)`
                            : `${Number(v || 0).toLocaleString("it-IT")} target`
                        }
                        return metricMode === "rev"
                          ? `€${Number(v || 0).toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                          : `${Number(v || 0).toLocaleString("it-IT")} pezzi`
                      }}
                    />
                    <Bar
                      dataKey={metricMode === "rev" ? "rev" : "qty"}
                      name={metricMode === "rev" ? "Fatturato" : "Pezzi"}
                      fill="#7b61ff"
                      radius={[0, 4, 4, 0]}
                    />
                    <Scatter
                      dataKey={metricMode === "rev" ? "targetRevImplied" : "targetQty"}
                      name="Target"
                      fill="#fbbf24"
                      shape={(props) => {
                        const { cx, cy, payload } = props
                        if (!payload) return null
                        const t =
                          metricMode === "rev"
                            ? Number(payload.targetRevImplied) || 0
                            : Number(payload.targetQty) || 0
                        if (t <= 0) return null
                        return <line x1={cx} y1={cy - 7} x2={cx} y2={cy + 7} stroke="#fbbf24" strokeWidth={3} strokeLinecap="round" />
                      }}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}

          </>
        )}

      </main>
    </div>
  )
}
