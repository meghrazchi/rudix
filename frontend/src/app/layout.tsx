import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppQueryProvider } from "@/components/providers/AppQueryProvider";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Rudix",
    template: "%s | Rudix",
  },
  description: "Rudix enterprise RAG platform",
  icons: {
    icon: "/brand/rudix-mark.svg",
    shortcut: "/brand/rudix-mark.svg",
    apple: "/brand/rudix-mark.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AppQueryProvider>{children}</AppQueryProvider>
      </body>
    </html>
  );
}
