import { useAuth } from "../hooks/useAuth";
import LoadingSpinner from "../components/LoadingSpinner.jsx";

export default function Profile() {
  const { user, loading } = useAuth();

  if (loading || !user) {
    return (
      <div className="flex justify-center py-16">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="mb-6 text-2xl font-bold text-slate-900">Your profile</h1>

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center gap-4 border-b border-slate-100 bg-slate-50 px-6 py-5">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-600 text-xl font-bold text-white">
            {user.username?.[0]?.toUpperCase()}
          </div>
          <div>
            <p className="text-lg font-semibold text-slate-900">
              {user.username}
            </p>
            <p className="text-sm capitalize text-slate-500">{user.role}</p>
          </div>
        </div>

        <dl className="divide-y divide-slate-100">
          <Row label="Email" value={user.email} />
          <Row label="Phone number" value={user.phone_number || "Not provided"} />
          <Row
            label="Phone verified"
            value={user.is_phone_verified ? "Yes" : "No"}
          />
          <Row label="Trust score" value={user.trust_score} />
          <Row label="Strikes" value={user.strike_count} />
          <Row
            label="Account status"
            value={user.is_restricted ? "Restricted" : "In good standing"}
          />
          <Row
            label="Member since"
            value={new Date(user.created_at).toLocaleDateString()}
          />
        </dl>
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between px-6 py-4">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="text-sm font-medium text-slate-900">{value}</dd>
    </div>
  );
}
