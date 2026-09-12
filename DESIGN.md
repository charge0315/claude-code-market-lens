---
name: Alpha Forge Terminal
description: >
  日本株 AI トレーディング端末のプロ向けビジュアルアイデンティティ。
  Bloomberg Terminal / MARKETSPEED II / TradingView に寄せた near-black ベース、
  高密度・低余白レイアウト、等幅数値、国内証券標準の騰落色（上げ赤／下げ緑）。
colors:
  bg-primary: "#0a0e14"
  bg-secondary: "#12161c"
  bg-tertiary: "#161b22"
  surface: "#1e242c"
  border: "#2a323d"
  border-active: "#1f6feb"
  text-primary: "#e6edf3"
  text-secondary: "#a0aec0"
  text-muted: "#8b949e"
  primary: "#1f6feb"
  accent-bright: "#3b82f6"
  accent-dim: "rgba(31, 111, 235, 0.15)"
  term-green: "#00c853"
  term-red: "#ff4d4f"
  term-blue: "#58a6ff"
  term-yellow: "#d29922"
  term-cyan: "#00b4d8"
  term-purple: "#bc8cff"
  gain: "{colors.term-red}"
  loss: "{colors.term-green}"
  flat: "{colors.text-muted}"
  gain-bg: "rgba(255, 77, 79, 0.12)"
  loss-bg: "rgba(0, 200, 83, 0.12)"
typography:
  display:
    fontFamily: "Archivo Black, Arial Black, sans-serif"
    fontSize: 1.5rem
  h1:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Inter, sans-serif"
    fontSize: 1.25rem
    fontWeight: 600
  body-md:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Inter, sans-serif"
    fontSize: 0.8125rem
  body-sm:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Inter, sans-serif"
    fontSize: 0.75rem
  label-caps:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Inter, sans-serif"
    fontSize: 0.6875rem
  numeric:
    fontFamily: "Consolas, Roboto Mono, SF Mono, JetBrains Mono, monospace"
    fontSize: 0.8125rem
    fontFeature: "tabular-nums"
rounded:
  sm: 2px
  md: 2px
  lg: 3px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  "2xl": 28px
  "3xl": 40px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: 8px
  button-primary-hover:
    backgroundColor: "{colors.accent-bright}"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: 12px
  modal:
    backgroundColor: "{colors.bg-secondary}"
    rounded: "{rounded.lg}"
    padding: 16px
  table-header:
    backgroundColor: "{colors.bg-tertiary}"
    textColor: "{colors.text-muted}"
    typography: "{typography.label-caps}"
---

## Overview

Architectural Minimalism meets プロ向け金融端末。個人投資家向けの明るく親しみやすい UI
ではなく、Bloomberg Terminal・MARKETSPEED II・TradingView のような「情報密度が高く、
装飾を削ぎ落とした」画面を志向する。near-black のベースにプライマリブルーの単一アクセント、
数値は等幅フォントで右寄せ・カンマ区切り・小数点位置を揃える。装飾的なシャドウやグラデーション
は使わず、影はほぼ 1px の罫線で表現する（`--shadow-sm` 参照）。

## Colors

パレットは「near-black の背景階層」「プライマリブルーの単一アクセント」「方向に依存しない
literal なターミナルカラー」「国内証券標準の騰落色セマンティック」の4層で構成する。

- **背景階層（bg-primary〜surface）**: `#0a0e14`（最背面）から `#1e242c`（カード等の前面
  サーフェス）まで4段階。層が上がるほど明るくなり、奥行きをフラットな面の重なりだけで表現する。
- **プライマリブルー（primary: #1f6feb）**: 唯一のインタラクション駆動色。ボタン・アクティブ
  タブ・フォーカスリング・リンクに使う。ホバー時は `accent-bright`（#3b82f6）へ明るくする。
- **ターミナルカラー（term-*）**: グラフの系列色・ステータスバッジ等、方向性を持たない用途。
- **騰落セマンティック（gain/loss/flat）**: **必ずこの3トークン経由**で使う。日本の証券会社
  標準に合わせ `gain`=赤（`term-red`）、`loss`=緑（`term-green`）。海外仕様（上げ緑）は
  絶対に直接指定しない — `gain`/`loss` の対応をこの1箇所で入れ替えるだけで全画面に反映される
  設計を維持すること。

## Typography

UI 本文には `-apple-system` 系のシステムフォントスタック（`font-ui`）、数値には等幅フォント
スタック（`font-mono`）を使い分ける。`display`（`font-display`: Archivo Black）はダッシュボード
等の大見出し専用で多用しない。

- 本文サイズは 0.6875rem（`xs`、キャプション・ラベル）〜 1rem（`xl`）の狭いレンジに収め、
  高密度な画面でも読みやすさを保つ。見出しのみ `2xl`（1.25rem）/`3xl`（1.5rem）を使う。
- **数値は必ず `font-variant-numeric: tabular-nums` + 等幅フォントで右寄せ**にする
  （価格・スコア・パーセンテージ等、桁がそろわないと比較しづらい値すべてに適用）。

## Layout

- スペーシングは 4px（`xs`）刻みの8段階（`xs`〜`3xl`）のみ使う。場当たり的な px 指定は禁止。
- サイドバー幅 220px・ヘッダー高 52px・マーケットバー高 30px を固定レイアウト値とする。
- レスポンシブブレークポイントは **640 / 768 / 900 / 1280 の4段のみ**
  （`__tests__/styles/breakpoints.test.ts` が強制、CLAUDE.md 参照）。

## Elevation & Depth

奥行きはぼかしシャドウではなく、背景階層の明度差 + 1px 罫線（`--color-border`）でほぼ表現する。
`shadow-sm`〜`shadow-lg` はいずれも薄いフラットな影（例: `shadow-md = 0 1px 2px rgba(0,0,0,0.5)`）
に留め、`shadow-glow-accent`（フォーカスリング用の1pxブルーグロー）以外で色付きシャドウは使わない。
モーダル等の一時的なオーバーレイのみ `shadow-lg` + 暗い半透明バックドロップ（`rgba(0,0,0,0.65)`）
を使ってよい。

## Components

- **button-primary**: プライマリブルーの塗り、シャープな角丸（`rounded.sm` = 2px）、ホバーで
  `accent-bright` へ明るく変化するのみ（拡大・影の追加はしない — `transform`/`opacity` 以外を
  アニメーションさせない方針、CLAUDE.md）。
- **card**: `surface` 背景 + `rounded.md`。パネル・データテーブルのコンテナに使う共通単位。
- **modal**: `bg-secondary` 背景・`rounded.lg`・`shadow-lg`。半透明バックドロップの中央に
  最大幅 768px で表示し、Escape キー / バックドロップクリックで閉じる。長文（ナレッジベース
  ノート本文・LLM 根拠詳細等）を表示する唯一の場所とし、通常のテーブル・カードには要約のみを
  置く。
- **table-header**: `bg-tertiary` 背景 + `text-muted` + `label-caps` タイポグラフィ。
  生 `<table>` は使わず、共通コンポーネント `components/ui/DataTable.tsx` 経由で統一する
  （`caption` 必須、CLAUDE.md）。

## Do's and Don'ts

- ✅ 騰落色は必ず `--color-gain`/`--color-loss`/`--color-flat` 経由で参照する。
- ✅ アニメーションは `transform`/`opacity` のみ。ホバーの拡大やシャドウ追加は避ける。
- ✅ 数値表示は等幅 + `tabular-nums` + 右寄せで統一する。
- ✅ 新規コンポーネントの色・余白・角丸は必ず `tokens.css` の CSS カスタムプロパティ経由で
  指定する（ハードコード禁止）。
- ❌ 海外仕様（上げ緑・下げ赤）を直接コードへ書かない。
- ❌ 装飾的なグラデーション・ぼかしシャドウ・派手なホバーエフェクトを追加しない
  （プロ端末の情報密度を優先し、コンシューマー向け UI の華やかさを持ち込まない）。
- ❌ ブレークポイントを 640/768/900/1280 以外で追加しない。
