"use client";

import { useEffect, useState } from "react";
import AuroraFlow from "./backgrounds/AuroraFlow";
import LiquidChroma from "./backgrounds/LiquidChroma";
import CyberGrid from "./backgrounds/CyberGrid";
import GlassOrbs from "./backgrounds/GlassOrbs";
import CosmicNebula from "./backgrounds/CosmicNebula";
import CharcoalGlow from "./backgrounds/CharcoalGlow";
import SynthwaveHorizon from "./backgrounds/SynthwaveHorizon";
import DigitalMatrix from "./backgrounds/DigitalMatrix";

export type BackgroundStyle =
  | "aurora-flow"
  | "liquid-chroma"
  | "cyber-grid"
  | "glass-orbs"
  | "cosmic-nebula"
  | "charcoal-glow"
  | "synthwave-horizon"
  | "digital-matrix";

export const ALL_BACKGROUND_STYLES: BackgroundStyle[] = [
  "aurora-flow",
  "liquid-chroma",
  "cyber-grid",
  "glass-orbs",
  "cosmic-nebula",
  "charcoal-glow",
  "synthwave-horizon",
  "digital-matrix",
];

interface AppBackgroundProps {
  className?: string;
}

const STORAGE_KEY = "videolens_bg_style";

export function getRandomBackgroundStyle(): BackgroundStyle {
  const randomIndex = Math.floor(Math.random() * ALL_BACKGROUND_STYLES.length);
  return ALL_BACKGROUND_STYLES[randomIndex];
}

export function getStoredBackgroundStyle(): BackgroundStyle {
  if (typeof window === "undefined") return ALL_BACKGROUND_STYLES[0];
  const manualChoice = sessionStorage.getItem("videolens_manual_bg");
  if (manualChoice && ALL_BACKGROUND_STYLES.includes(manualChoice as BackgroundStyle)) {
    return manualChoice as BackgroundStyle;
  }
  return getRandomBackgroundStyle();
}

export function setStoredBackgroundStyle(style: BackgroundStyle): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem("videolens_manual_bg", style);
  localStorage.setItem(STORAGE_KEY, style);
  window.dispatchEvent(new CustomEvent("videolens-bg-change", { detail: style }));
}

export function AppBackground({ className = "" }: AppBackgroundProps) {
  const [bgStyle, setBgStyle] = useState<BackgroundStyle>("aurora-flow");

  useEffect(() => {
    // Runs on client after hydration completes, safely applying random background
    setBgStyle(getStoredBackgroundStyle());

    const handleBgChange = (e: Event) => {
      const customEvent = e as CustomEvent<BackgroundStyle>;
      if (customEvent.detail) {
        setBgStyle(customEvent.detail);
      }
    };

    window.addEventListener("videolens-bg-change", handleBgChange);
    return () => window.removeEventListener("videolens-bg-change", handleBgChange);
  }, []);

  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none fixed inset-0 transition-opacity duration-700 ${className}`}
      style={{ zIndex: "var(--z-background)" }}
    >
      {bgStyle === "aurora-flow" && <AuroraFlow />}
      {bgStyle === "liquid-chroma" && <LiquidChroma />}
      {bgStyle === "cyber-grid" && <CyberGrid />}
      {bgStyle === "glass-orbs" && <GlassOrbs />}
      {bgStyle === "cosmic-nebula" && <CosmicNebula />}
      {bgStyle === "charcoal-glow" && <CharcoalGlow />}
      {bgStyle === "synthwave-horizon" && <SynthwaveHorizon />}
      {bgStyle === "digital-matrix" && <DigitalMatrix />}
    </div>
  );
}
