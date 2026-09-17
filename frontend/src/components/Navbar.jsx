import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

export default function Navbar() {
  const { isAuthenticated, user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <header className="border-b border-slate-200 bg-white">
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <Link to="/" className="flex items-center gap-2 text-xl font-bold text-slate-900">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
            N
          </span>
          NoTox
        </Link>

        <div className="flex items-center gap-6 text-sm font-medium text-slate-600">
          {isAuthenticated ? (
            <>
              <Link to="/dashboard" className="hover:text-brand-600">
                Dashboard
              </Link>
              <Link to="/profile" className="flex items-center gap-2 hover:text-brand-600">
                <span className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-brand-600 text-xs font-bold text-white">
                  {user?.avatar ? (
                    <img
                      src={user.avatar}
                      alt={user.display_name || user.username}
                      className="h-full w-full object-cover"
                      onError={(e) => {
                        e.target.style.display = "none";
                      }}
                    />
                  ) : (
                    user?.username?.[0]?.toUpperCase()
                  )}
                </span>
                <span className="hidden sm:inline">
                  {user?.display_name || user?.username}
                </span>
              </Link>
              <button
                onClick={handleLogout}
                className="rounded-lg bg-slate-900 px-4 py-2 text-white transition hover:bg-slate-700"
              >
                Logout
              </button>

            </>
          ) : (
            <>
              <Link to="/login" className="hover:text-brand-600">
                Login
              </Link>
              <Link
                to="/register"
                className="rounded-lg bg-brand-600 px-4 py-2 text-white transition hover:bg-brand-700"
              >
                Sign up
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
