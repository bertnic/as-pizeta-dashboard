import { useState, useEffect } from "react"
import { HashRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom"
import LoginPage from "./pages/LoginPage"
import TwoFAPage from "./pages/TwoFAPage"
import DashboardPage from "./pages/DashboardPage"

export default function App() {
  const [user, setUser] = useState(undefined)

  useEffect(() => {
    fetch(import.meta.env.BASE_URL + "auth/me").then(r => r.json()).then(d => setUser(d.user || null))
  }, [])

  if (user === undefined) return (
    <div className="splash">
      <div className="spinner" />
    </div>
  )

  return (
    <HashRouter>
      <Routes>
        <Route path="/auth" element={<LoginPage setUser={setUser} />} />
        <Route path="/2fa" element={<TwoFAPage setUser={setUser} />} />
        <Route path="/" element={user ? <DashboardPage user={user} setUser={setUser} /> : <Navigate to="/auth" />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </HashRouter>
  )
}
