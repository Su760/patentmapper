"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { createClient } from "@/lib/supabase";

export default function NavBar() {
  const { user, loading } = useAuth();

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
  }

  return (
    <nav className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
      <Link
        href="/"
        className="text-white font-bold text-lg tracking-tight hover:opacity-80 transition-opacity"
      >
        Patent<span className="text-blue-400">Mapper</span>
      </Link>

      {loading ? (
        <div className="w-24 h-4 bg-gray-800 rounded animate-pulse" />
      ) : (
        <div className="flex items-center gap-4">
          {user ? (
            <>
              <span className="text-gray-400 text-sm hidden sm:block">
                {user.email && user.email.length > 20
                  ? user.email.slice(0, 20) + "…"
                  : user.email}
              </span>
              <Link
                href="/pricing"
                className="text-gray-400 hover:text-gray-200 text-sm transition-colors"
              >
                Pricing
              </Link>
              <button
                onClick={handleSignOut}
                className="text-gray-400 hover:text-gray-200 text-sm transition-colors"
              >
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link
                href="/dashboard"
                className="text-gray-400 hover:text-gray-200 text-sm transition-colors"
              >
                Dashboard
              </Link>
              <Link
                href="/pricing"
                className="text-gray-400 hover:text-gray-200 text-sm transition-colors"
              >
                Pricing
              </Link>
              <Link
                href="/auth"
                className="text-gray-400 hover:text-gray-200 text-sm transition-colors"
              >
                Sign in
              </Link>
            </>
          )}
        </div>
      )}
    </nav>
  );
}
