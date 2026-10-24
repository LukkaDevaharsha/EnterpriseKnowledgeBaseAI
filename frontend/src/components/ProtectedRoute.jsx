import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/useAuth'

export default function ProtectedRoute({ children }) {
  const { token, user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="route-loading" role="status">Restoring your session…</div>
  if (!token || !user) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}
