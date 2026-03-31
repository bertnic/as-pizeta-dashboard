import { useState, useEffect, useRef } from "react"
import { useNavigate } from "react-router-dom"
import appLogo from "../assets/logo.svg"

export default function TwoFAPage({ setUser }) {
  const [qr, setQr] = useState(null)
  const [secret, setSecret] = useState(null)
  const [code, setCode] = useState(["", "", "", "", "", ""])
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [showQr, setShowQr] = useState(false)
  const navigate = useNavigate()
  const inputs = useRef([])

  useEffect(() => {
    fetch(import.meta.env.BASE_URL + "auth/2fa/qr").then(r => r.json()).then(d => {
      if (d.qr) { setQr(d.qr); setSecret(d.secret) }
    })
  }, [])

  const handleDigit = (i, val) => {
    if (!/^\d?$/.test(val)) return
    const next = [...code]
    next[i] = val
    setCode(next)
    if (val && i < 5) inputs.current[i + 1]?.focus()
  }

  const handleKey = (i, e) => {
    if (e.key === "Backspace" && !code[i] && i > 0) inputs.current[i - 1]?.focus()
  }

  const handlePaste = (e) => {
    const text = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6)
    if (text.length === 6) setCode(text.split(""))
  }

  const verify = async () => {
    const full = code.join("")
    if (full.length < 6) return
    setLoading(true); setError("")
    const r = await fetch(import.meta.env.BASE_URL + "auth/2fa/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: full })
    })
    const d = await r.json()
    setLoading(false)
    if (d.ok) { setUser(d.user); navigate("/") }
    else { setError("Codice non valido. Riprova."); setCode(["", "", "", "", "", ""]); inputs.current[0]?.focus() }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card twofa-card">
        <div className="auth-logo">
          <img className="logo-icon" src={appLogo} alt="Pizeta logo" />
        </div>
        <h2 className="twofa-title">Verifica in due passaggi</h2>
        <p className="twofa-desc">Inserisci il codice dalla tua app di autenticazione</p>

        <div className="code-inputs" onPaste={handlePaste}>
          {code.map((d, i) => (
            <input key={i} ref={el => inputs.current[i] = el}
              className="code-digit" maxLength={1} value={d}
              onChange={e => handleDigit(i, e.target.value)}
              onKeyDown={e => handleKey(i, e)}
              inputMode="numeric" autoFocus={i === 0}
            />
          ))}
        </div>

        {error && <p className="twofa-error">{error}</p>}

        <button className="btn-verify" onClick={verify} disabled={loading || code.join("").length < 6}>
          {loading ? <span className="spinner-sm" /> : "Verifica"}
        </button>

        <button className="btn-link" onClick={() => setShowQr(!showQr)}>
          {showQr ? "Nascondi QR" : "Prima volta? Scansiona il QR"}
        </button>

        {showQr && qr && (
          <div className="qr-container">
            <img src={qr} alt="QR Code" className="qr-img" />
            <p className="qr-secret">Chiave manuale: <code>{secret}</code></p>
          </div>
        )}
      </div>
    </div>
  )
}
