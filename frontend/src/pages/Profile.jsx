import { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import LoadingSpinner from "../components/LoadingSpinner.jsx";
import { getErrorMessage } from "../services/api";

export default function Profile() {
  const { user, loading, updateProfile } = useAuth();
  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState({
    display_name: "",
    bio: "",
    avatar: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [avatarLoadError, setAvatarLoadError] = useState(false);

  if (loading || !user) {
    return (
      <div className="flex justify-center py-16">
        <LoadingSpinner />
      </div>
    );
  }

  const handleStartEdit = () => {
    setFormData({
      display_name: user.display_name || "",
      bio: user.bio || "",
      avatar: user.avatar || "",
    });
    setError("");
    setSuccessMessage("");
    setAvatarLoadError(false);
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    setSuccessMessage("");

    try {
      await updateProfile({
        display_name: formData.display_name.trim(),
        bio: formData.bio.trim(),
        avatar: formData.avatar.trim(),
      });
      setSuccessMessage("Profile updated successfully!");
      setIsEditing(false);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const trustScore = user.trust_score ?? 100;

  // Visual text bar calculation (20 blocks)
  const totalBlocks = 20;
  const filledBlocks = Math.round((Math.max(0, Math.min(100, trustScore)) / 100) * totalBlocks);
  const textBar = "█".repeat(filledBlocks) + "░".repeat(totalBlocks - filledBlocks);

  // Trust score status tier
  const getTrustStatus = (score) => {
    if (score >= 80) return { label: "Excellent", color: "text-emerald-700 bg-emerald-50 border-emerald-200", barColor: "bg-emerald-500" };
    if (score >= 50) return { label: "Good", color: "text-amber-700 bg-amber-50 border-amber-200", barColor: "bg-amber-500" };
    if (score >= 30) return { label: "Fair", color: "text-orange-700 bg-orange-50 border-orange-200", barColor: "bg-orange-500" };
    return { label: "At Risk", color: "text-rose-700 bg-rose-50 border-rose-200", barColor: "bg-rose-500" };
  };

  const trustStatus = getTrustStatus(trustScore);

  const getRoleBadge = (role) => {
    switch (role?.toLowerCase()) {
      case "admin":
        return <span className="rounded-full border border-purple-200 bg-purple-100 px-3 py-0.5 text-xs font-semibold text-purple-800">Admin</span>;
      case "moderator":
        return <span className="rounded-full border border-blue-200 bg-blue-100 px-3 py-0.5 text-xs font-semibold text-blue-800">Moderator</span>;
      default:
        return <span className="rounded-full border border-slate-200 bg-slate-100 px-3 py-0.5 text-xs font-semibold text-slate-700">User</span>;
    }
  };

  const displayName = user.display_name || user.username;
  const showAvatarImage = user.avatar && !avatarLoadError;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Your profile</h1>
          <p className="text-sm text-slate-500">Manage your profile identity and check your trust standing.</p>
        </div>
        {!isEditing && (
          <button
            onClick={handleStartEdit}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-brand-700"
          >
            Edit Profile
          </button>
        )}
      </div>

      {successMessage && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
          {successMessage}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          {error}
        </div>
      )}

      {/* Main Profile Header Card */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center gap-5 border-b border-slate-100 bg-slate-50 px-6 py-6">
          <div className="relative flex h-20 w-20 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-600 text-2xl font-bold text-white shadow-sm ring-4 ring-white">
            {showAvatarImage ? (
              <img
                src={user.avatar}
                alt={displayName}
                className="h-full w-full object-cover"
                onError={() => setAvatarLoadError(true)}
              />
            ) : (
              <span>{user.username?.[0]?.toUpperCase()}</span>
            )}
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-bold text-slate-900">{displayName}</h2>
              {getRoleBadge(user.role)}
            </div>
            <p className="text-sm text-slate-500">@{user.username}</p>
            {user.bio ? (
              <p className="text-sm text-slate-700 pt-1">{user.bio}</p>
            ) : (
              <p className="text-sm italic text-slate-400 pt-1">No bio added yet.</p>
            )}
          </div>
        </div>

        {/* Edit Form or Details View */}
        {isEditing ? (
          <form onSubmit={handleSubmit} className="p-6 space-y-5">
            <h3 className="text-base font-semibold text-slate-900 border-b border-slate-100 pb-2">
              Edit Profile Information
            </h3>

            <div>
              <label htmlFor="display_name" className="block text-sm font-medium text-slate-700">
                Display Name
              </label>
              <input
                type="text"
                id="display_name"
                maxLength={150}
                value={formData.display_name}
                onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                placeholder="e.g. Jane Doe"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
              <p className="mt-1 text-xs text-slate-500">How your name appears to other users.</p>
            </div>

            <div>
              <label htmlFor="bio" className="block text-sm font-medium text-slate-700">
                Bio
              </label>
              <textarea
                id="bio"
                rows={3}
                value={formData.bio}
                onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                placeholder="Share a brief description about yourself..."
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>

            <div>
              <label htmlFor="avatar" className="block text-sm font-medium text-slate-700">
                Avatar Image URL
              </label>
              <input
                type="url"
                id="avatar"
                value={formData.avatar}
                onChange={(e) => setFormData({ ...formData, avatar: e.target.value })}
                placeholder="https://example.com/avatar.jpg"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
              <p className="mt-1 text-xs text-slate-500">Provide a direct link to an image (HTTPS recommended).</p>
            </div>

            {formData.avatar && (
              <div className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3">
                <span className="text-xs font-medium text-slate-600">Preview:</span>
                <img
                  src={formData.avatar}
                  alt="Avatar preview"
                  className="h-10 w-10 rounded-full object-cover border border-slate-200"
                  onError={(e) => {
                    e.target.style.display = "none";
                  }}
                />
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleCancelEdit}
                disabled={saving}
                className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-brand-700 disabled:opacity-50"
              >
                {saving && <LoadingSpinner size="sm" />}
                {saving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </form>
        ) : null}
      </div>

      {/* Trust Score Foundation Card */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Trust Score</h2>
            <p className="text-xs text-slate-500">Network credibility & moderation standing</p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${trustStatus.color}`}>
              {trustStatus.label}
            </span>
            <span className="text-xl font-bold text-slate-900">{trustScore}/100</span>
          </div>
        </div>

        {/* Progress bar visual */}
        <div className="space-y-2">
          <div className="h-3.5 w-full overflow-hidden rounded-full bg-slate-100 p-0.5 ring-1 ring-inset ring-slate-200">
            <div
              className={`h-full rounded-full transition-all duration-500 ${trustStatus.barColor}`}
              style={{ width: `${Math.max(0, Math.min(100, trustScore))}%` }}
            />
          </div>

          {/* ASCII / Monospace Visual Representation */}
          <div className="flex items-center justify-between text-xs text-slate-500 font-mono pt-1">
            <span className="text-slate-700 font-semibold">{textBar}</span>
            <span>{trustScore}/100</span>
          </div>
        </div>

        <p className="mt-4 text-xs text-slate-500">
          All new accounts start with a full score of 100. Your score remains positive as long as your interactions adhere to community standards.
        </p>
      </div>

      {/* Account Details Card */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 bg-slate-50 px-6 py-4">
          <h2 className="text-base font-semibold text-slate-900">Account Details</h2>
        </div>
        <dl className="divide-y divide-slate-100">
          <Row label="Username" value={`@${user.username}`} />
          <Row label="Display Name" value={user.display_name || "Not set"} />
          <Row label="Email" value={user.email} />
          <Row label="Phone number" value={user.phone_number || "Not provided"} />
          <Row
            label="Phone verified"
            value={user.is_phone_verified ? "Yes" : "No"}
          />
          <Row label="Role" value={<span className="capitalize">{user.role}</span>} />
          <Row label="Trust score" value={`${user.trust_score}/100`} />
          <Row label="Strikes" value={user.strike_count} />
          <Row
            label="Account status"
            value={
              <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                user.is_restricted ? "bg-rose-100 text-rose-800" : "bg-emerald-100 text-emerald-800"
              }`}>
                {user.is_restricted ? "Restricted" : "In good standing"}
              </span>
            }
          />
          <Row
            label="Member since"
            value={new Date(user.created_at).toLocaleDateString(undefined, {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
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

