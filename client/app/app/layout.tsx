import type { Metadata } from "next";
import { Noto_Sans_JP, Geist_Mono } from "next/font/google";
import "./globals.css";
import { TooltipProvider } from "@/components/ui/tooltip";

const notoSansJP = Noto_Sans_JP({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "RemoteLife Tokyo — リモート暮らしマップ",
  description:
    "リモートワーク前提の暮らしやすさで、東京都内の区市町村を比較できるインタラクティブ地図サービス。6つの評価軸をカスタマイズして、あなたに合った街を見つけよう。",
  keywords: [
    "リモートワーク",
    "東京",
    "暮らしやすさ",
    "移住",
    "テレワーク",
    "区市町村比較",
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ja"
      className={`${notoSansJP.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-sans">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
