import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../services/api.js";
import { streamService } from "../services/streamService.js";

export default function StreamList() {
  const [streams, setStreams] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setStreams(await streamService.list());
      setError("");
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="mx-auto max-w-3xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Live streams</h1>
        <Link to="/streams/go-live" className="rounded bg-red-600 px-4 py-2 text-white">
          Go live
        </Link>
      </div>
      {error && <p className="mb-4 text-red-500">{error}</p>}
      {loading && <p>Loading…</p>}
      {!loading && streams.length === 0 && <p>No one is live right now.</p>}
      <ul className="space-y-3">
        {streams.map((s) => (
          <li key={s.id} className="flex items-center justify-between rounded border p-4">
            <div>
              <p className="font-semibold">{s.title}</p>
              <p className="text-sm text-gray-500">by {s.host_username}</p>
            </div>
            <Link to={`/watch/${s.id}`} className="rounded bg-blue-600 px-3 py-1 text-white">
              Watch
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}