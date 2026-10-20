import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "wallet-classifier",
  description: "Bot ou humain ? Analyse comportementale d'une adresse Ethereum (POC).",
};

// applique le thème avant l'affichage (évite le flash) ; sombre par défaut
const THEME_SCRIPT = `try{var t=localStorage.getItem("wc_theme");document.documentElement.dataset.theme=t==="light"?"light":"dark"}catch(e){document.documentElement.dataset.theme="dark"}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen">
        <Nav />
        <main className="mx-auto w-full max-w-5xl px-4 py-12">{children}</main>
        <footer className="mx-auto max-w-5xl border-t border-grid px-4 py-8 text-xs leading-5 text-muted">
          Preuve de concept : dataset de 85 wallets, labels en partie heuristiques. La probabilité affichée n&apos;est
          pas calibrée : c&apos;est un indice de ressemblance avec les données d&apos;entraînement.
        </footer>
      </body>
    </html>
  );
}
