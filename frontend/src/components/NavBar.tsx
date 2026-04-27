"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { createClient } from "@/lib/supabase";

function Wordmark() {
  return (
    <Link href="/" className="pm-wordmark" style={{ textDecoration: "none" }}>
      <div className="pm-wordmark-glyph" />
      <span>PatentMapper</span>
    </Link>
  );
}

export default function NavBar() {
  const { user, loading } = useAuth();

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
  }

  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "??";

  return (
    <nav className="pm-nav">
      <Wordmark />
      <div className="pm-nav-links">
        {loading ? (
          <div
            style={{
              width: 80,
              height: 16,
              background: "var(--surface)",
              borderRadius: 4,
            }}
          />
        ) : user ? (
          <>
            <Link href="/dashboard" className="pm-nav-link">
              Dashboard
            </Link>
            <Link href="/pricing" className="pm-nav-link">
              Pricing
            </Link>
            <span
              style={{
                width: 1,
                height: 16,
                background: "var(--border)",
                margin: "0 6px",
              }}
            />
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "0 6px",
              }}
            >
              <div
                title={user.email ?? undefined}
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 999,
                  background: "linear-gradient(135deg, #6ea8ff, #c084fc)",
                  fontSize: 10,
                  color: "white",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
                onClick={handleSignOut}
              >
                {initials}
              </div>
            </div>
          </>
        ) : (
          <>
            <Link href="/pricing" className="pm-nav-link">
              Pricing
            </Link>
            <Link href="/dashboard" className="pm-nav-link">
              Docs
            </Link>
            <span
              style={{
                width: 1,
                height: 16,
                background: "var(--border)",
                margin: "0 6px",
              }}
            />
            <Link href="/auth" className="pm-nav-link">
              Sign in
            </Link>
            <Link
              href="/auth"
              className="pm-btn sm"
              style={{
                marginLeft: 6,
                background: "var(--text)",
                color: "var(--bg)",
                borderColor: "transparent",
                textDecoration: "none",
              }}
            >
              Try free →
            </Link>
          </>
        )}
      </div>
    </nav>
  );
}
