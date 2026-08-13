"use client";

import { useEffect, useState } from "react";
import { Check, Dices, Palette, Sparkles, Wand2 } from "lucide-react";
import {
  type BackgroundStyle,
  getRandomBackgroundStyle,
  getStoredBackgroundStyle,
  setStoredBackgroundStyle,
} from "./AppBackground";

type ThemeCategory = "all" | "shaders" | "cyber" | "ambient";

const BACKGROUND_OPTIONS: {
  id: BackgroundStyle;
  name: string;
  desc: string;
  gradient: string;
  category: "shaders" | "cyber" | "ambient";
  badge: string;
}[] = [
  {
    id: "aurora-flow",
    name: "Aurora Flow",
    desc: "Fluid WebGL noise shader with smooth purple & cyan liquid flow",
    gradient: "from-purple-600 via-indigo-600 to-cyan-500",
    category: "shaders",
    badge: "WebGL Fluid",
  },
  {
    id: "liquid-chroma",
    name: "Liquid Chromatic Wave",
    desc: "Shimmering metallic iridescent oil-slick surface shader",
    gradient: "from-cyan-500 via-pink-500 to-amber-400",
    category: "shaders",
    badge: "Iridescent",
  },
  {
    id: "cyber-grid",
    name: "Cyber Grid",
    desc: "High-tech dot matrix grid with soft glowing scanning beams",
    gradient: "from-indigo-900 via-slate-900 to-cyan-950",
    category: "cyber",
    badge: "Matrix Grid",
  },
  {
    id: "glass-orbs",
    name: "Neon Orbs",
    desc: "Floating luminous blurred spheres with frosted glass depth",
    gradient: "from-fuchsia-600 via-purple-700 to-pink-600",
    category: "ambient",
    badge: "Neon Glass",
  },
  {
    id: "cosmic-nebula",
    name: "Cosmic Starfield",
    desc: "Deep space starry dust cloud with swirling galactic clouds",
    gradient: "from-purple-900 via-blue-950 to-pink-900",
    category: "ambient",
    badge: "Galactic",
  },
  {
    id: "charcoal-glow",
    name: "Charcoal Glow",
    desc: "Ultra-clean dark matte background with soft corner spotlighting",
    gradient: "from-zinc-800 via-zinc-900 to-slate-950",
    category: "ambient",
    badge: "Minimalist",
  },
  {
    id: "synthwave-horizon",
    name: "Synthwave Horizon",
    desc: "Retro 80s 3D perspective grid with a glowing neon horizon sun",
    gradient: "from-fuchsia-700 via-purple-900 to-yellow-500",
    category: "cyber",
    badge: "Retro 80s",
  },
  {
    id: "digital-matrix",
    name: "Matrix Rain",
    desc: "Cyberpunk glowing digital code streams falling down canvas",
    gradient: "from-emerald-900 via-slate-950 to-emerald-600",
    category: "cyber",
    badge: "Cyber Code",
  },
];

export function BackgroundPickerPanel() {
  const [currentStyle, setCurrentStyle] = useState<BackgroundStyle>("aurora-flow");
  const [selectedCategory, setSelectedCategory] = useState<ThemeCategory>("all");

  useEffect(() => {
    setCurrentStyle(getStoredBackgroundStyle());
    const handleBgChange = (e: Event) => {
      const customEvent = e as CustomEvent<BackgroundStyle>;
      if (customEvent.detail) {
        setCurrentStyle(customEvent.detail);
      }
    };
    window.addEventListener("videolens-bg-change", handleBgChange);
    return () => window.removeEventListener("videolens-bg-change", handleBgChange);
  }, []);

  const handleRandomize = () => {
    const nextRandom = getRandomBackgroundStyle();
    setCurrentStyle(nextRandom);
    setStoredBackgroundStyle(nextRandom);
  };

  const filteredOptions = BACKGROUND_OPTIONS.filter((opt) =>
    selectedCategory === "all" ? true : opt.category === selectedCategory
  );

  const activeThemeObj = BACKGROUND_OPTIONS.find((b) => b.id === currentStyle);

  return (
    <div className="flex flex-col gap-4">
      {/* Top Banner Control Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-[var(--color-rule-strong)] bg-[var(--color-paper-2)] p-3.5 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-accent-soft)] text-[var(--color-accent)] border border-[var(--color-accent)] shadow-sm shrink-0">
            <Palette className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[var(--color-text-strong)]">
                Active Theme:
              </span>
              <span className="rounded-full bg-[var(--color-accent-soft)] px-2.5 py-0.5 text-[11px] font-bold text-[var(--color-accent-hover)] border border-[var(--color-accent)]/30">
                {activeThemeObj?.name || "Aurora Flow"}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-[var(--color-muted)]">
              8 live themes available. Random pick active on fresh page open.
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={handleRandomize}
          className="group flex items-center justify-center gap-2 rounded-lg border border-amber-500/40 bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-amber-500/20 px-4 py-2 text-xs font-bold text-amber-300 shadow-md transition-all duration-200 hover:scale-105 hover:border-amber-400 hover:bg-amber-500/30 shrink-0"
        >
          <Dices className="h-4 w-4 text-amber-400 transition-transform duration-300 group-hover:rotate-180" />
          <span>Shuffle Random</span>
          <Sparkles className="h-3 w-3 text-amber-400" />
        </button>
      </div>

      {/* Category Pills */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        {[
          { id: "all", label: "All Themes (8)" },
          { id: "shaders", label: "WebGL Shaders" },
          { id: "cyber", label: "Cyber & Retro" },
          { id: "ambient", label: "Ambient & Minimal" },
        ].map((cat) => (
          <button
            key={cat.id}
            type="button"
            onClick={() => setSelectedCategory(cat.id as ThemeCategory)}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-all shrink-0 ${
              selectedCategory === cat.id
                ? "bg-[var(--color-text-strong)] text-zinc-950 font-bold shadow-sm"
                : "bg-[var(--color-paper-2)] text-[var(--color-muted)] border border-[var(--color-rule)] hover:text-[var(--color-text)] hover:bg-[var(--color-paper-3)]"
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Responsive Gallery Grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {filteredOptions.map((opt) => {
          const isActive = currentStyle === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => {
                setCurrentStyle(opt.id);
                setStoredBackgroundStyle(opt.id);
              }}
              className={`group relative flex flex-col justify-between overflow-hidden rounded-xl border p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 ${
                isActive
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] shadow-xl shadow-indigo-950/40 ring-1 ring-[var(--color-accent)]"
                  : "border-[var(--color-rule-strong)] bg-[var(--color-paper-2)] hover:border-[var(--color-rule)] hover:bg-[var(--color-paper-3)]"
              }`}
            >
              {/* Preview Gradient Bar */}
              <div
                className={`h-16 w-full rounded-lg bg-gradient-to-r ${opt.gradient} relative overflow-hidden shadow-inner border border-white/10`}
              >
                {/* Sheen sheen effect */}
                <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-white/10" />

                <span className="absolute top-2 left-2 rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-bold text-white/90 backdrop-blur-md border border-white/10">
                  {opt.badge}
                </span>

                {isActive && (
                  <div className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-white text-indigo-950 shadow-md">
                    <Check className="h-3.5 w-3.5 stroke-[3]" />
                  </div>
                )}
              </div>

              {/* Title, Description & Action */}
              <div className="mt-3 flex items-start justify-between gap-2">
                <div>
                  <span className="text-sm font-bold text-[var(--color-text-strong)] group-hover:text-white">
                    {opt.name}
                  </span>
                  <p className="mt-1 text-xs leading-4 text-[var(--color-faint)]">
                    {opt.desc}
                  </p>
                </div>

                <span
                  className={`mt-0.5 rounded-md px-2 py-0.5 text-[10px] font-bold shrink-0 transition-colors ${
                    isActive
                      ? "bg-[var(--color-accent)] text-white"
                      : "bg-[var(--color-paper-3)] text-[var(--color-muted)] group-hover:text-[var(--color-text-strong)]"
                  }`}
                >
                  {isActive ? "Active" : "Apply"}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
