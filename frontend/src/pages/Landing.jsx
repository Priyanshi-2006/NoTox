import { Link } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

export default function Landing() {
  const { isAuthenticated } = useAuth();

  return (
    <div className="flex flex-col items-center justify-center gap-6 py-16 text-center">
      <span className="rounded-full bg-brand-50 px-4 py-1 text-sm font-medium text-brand-700">
        Stage 1 — Authentication & Identity
      </span>
      <h1 className="max-w-2xl text-4xl font-bold text-slate-900 sm:text-5xl">
        A social platform that's{" "}
        <span className="text-brand-600">moderated by design</span>, not by
        luck.
      </h1>
      <p className="max-w-xl text-slate-600">
        NoTox is being built incrementally. This stage lays the foundation:
        accounts, JWT authentication and role-aware profiles that every
        later feature — feeds, chat, moderation, trust scoring — will build
        on top of.
      </p>
      <div className="flex gap-4">
        {isAuthenticated ? (
          <Link
            to="/dashboard"
            className="rounded-lg bg-brand-600 px-6 py-3 font-medium text-white transition hover:bg-brand-700"
          >
            Go to dashboard
          </Link>
        ) : (
          <>
            <Link
              to="/register"
              className="rounded-lg bg-brand-600 px-6 py-3 font-medium text-white transition hover:bg-brand-700"
            >
              Create an account
            </Link>
            <Link
              to="/login"
              className="rounded-lg border border-slate-300 px-6 py-3 font-medium text-slate-700 transition hover:bg-slate-100"
            >
              Log in
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
