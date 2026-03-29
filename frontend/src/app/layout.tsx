import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import NavBar from "@/components/NavBar";

export const metadata: Metadata = {
  title: "PatentMapper — Map the Prior Art",
  description:
    "AI-powered patent landscape analysis. Find white space, prior art clusters, and opportunity gaps.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="bg-gray-950">
      <body className="bg-gray-950 text-gray-100 antialiased min-h-screen">
        <AuthProvider>
          <NavBar />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
