import { Link } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

export default function Dashboard() {
  const { user } = useAuth();

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          Welcome to NoTox{user ? `, ${user.username}` : ""}
        </h1>
        <p className="mt-1 text-slate-500">
          This is Stage 1 — authentication only. The feed, chat and
          moderation tools arrive in later stages.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Role" value={user?.role} />
        <StatCard label="Trust score" value={user?.trust_score} />
        <StatCard label="Strikes" value={user?.strike_count} />
      </div>

      <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-500">
        <p className="font-medium text-slate-700">Nothing here yet</p>
        <p className="mt-1 text-sm">
          The community feed, posts and real-time chat will show up here in
          later stages.
        </p>
        <Link
          to="/profile"
          className="mt-4 inline-block text-sm font-medium text-brand-600 hover:underline"
        >
          View your profile →
        </Link>
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold capitalize text-slate-900">
        {value ?? "—"}
      </p>
    </div>
  );
}
