import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Argus",
  description: "Real-time market intelligence",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={ibmPlexMono.variable}>
      <body
        className="min-h-screen w-full antialiased"
        style={{ background: "#0a0a0a", fontFamily: "var(--font-mono), monospace" }}
      >
        {children}
      </body>
    </html>
  );
}
