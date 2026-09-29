import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { PreferencesProvider } from "../lib/preferences";
import { Shell } from "../components/Shell";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "NEXUS — Inteligência Elétrica",
  description:
    "Monitoramento elétrico em tempo real: telemetria, diagnósticos de anomalias e detecção de eventos.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="pt-BR"
      data-theme="dark"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <PreferencesProvider>
          <Shell>{children}</Shell>
        </PreferencesProvider>
      </body>
    </html>
  );
}
