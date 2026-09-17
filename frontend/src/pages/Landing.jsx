import { Link } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

export default function Landing() {
  const { isAuthenticated } = useAuth();

  return (
    <div className="flex flex-col items-center justify-center gap-6 py-16 text-center">
      <span className="rounded-full bg-brand-50 px-4 py-1 text-sm font-medium text-brand-700">
        Intelligent Real-Time Moderation
      </span>
      <h1 className="max-w-2xl text-4xl font-bold text-slate-900 sm:text-5xl">
        A social platform that's{" "}
        <span className="text-brand-600">moderated by design</span>, not by
        luck.
      </h1>
      <p className="max-w-xl text-slate-600">
        Next-generation contextual and visual moderation platform for online chat,
        livestreaming, and community interactions. Experience a safer online space
        with transparent trust ratings and role-based protection.
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
