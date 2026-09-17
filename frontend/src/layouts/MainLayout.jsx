import Navbar from "../components/Navbar.jsx";

export default function MainLayout({ children }) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <Navbar />
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">{children}</main>
      <footer className="border-t border-slate-200 py-6 text-center text-xs text-slate-400">
        NoTox — Stage 1: Authentication & Identity
      </footer>
    </div>
  );
}
