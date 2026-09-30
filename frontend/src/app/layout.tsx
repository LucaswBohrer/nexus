import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { PreferencesProvider } from "../lib/preferences";
import { EquipmentProvider } from "../lib/equipment";
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
      <head>
        {/* Aplica tema/densidade salvos antes da primeira pintura,
            evitando flash do tema padrão. Sem dependências externas. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var p=JSON.parse(localStorage.getItem("nexus:preferences:v1")||"{}");var r=document.documentElement;if(p.theme==="light"||p.theme==="dark")r.dataset.theme=p.theme;if(p.density==="compact"||p.density==="comfortable")r.dataset.density=p.density;if(p.language)r.lang=p.language;}catch(e){}})();`,
          }}
        />
      </head>
      <body className="min-h-full">
        <PreferencesProvider>
          <EquipmentProvider>
            <Shell>{children}</Shell>
          </EquipmentProvider>
        </PreferencesProvider>
      </body>
    </html>
  );
}
