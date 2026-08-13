"use client";

import { useEffect, useRef } from "react";

export default function CyberGrid() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let time = 0;

    const render = () => {
      time += 0.015;
      const w = (canvas.width = canvas.clientWidth);
      const h = (canvas.height = canvas.clientHeight);

      ctx.fillStyle = "#07090e";
      ctx.fillRect(0, 0, w, h);

      const cx = w * (0.5 + Math.sin(time * 0.5) * 0.25);
      const cy = h * (0.4 + Math.cos(time * 0.3) * 0.2);

      const radGrad = ctx.createRadialGradient(cx, cy, 50, cx, cy, Math.max(w, h) * 0.6);
      radGrad.addColorStop(0, "rgba(99, 102, 241, 0.22)");
      radGrad.addColorStop(0.5, "rgba(168, 85, 247, 0.1)");
      radGrad.addColorStop(1, "rgba(7, 9, 14, 0)");
      ctx.fillStyle = radGrad;
      ctx.fillRect(0, 0, w, h);

      const spacing = 36;
      for (let x = spacing / 2; x < w; x += spacing) {
        for (let y = spacing / 2; y < h; y += spacing) {
          const dx = x - cx;
          const dy = y - cy;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const intensity = Math.max(0.08, 1 - dist / 450);
          ctx.fillStyle = `rgba(165, 180, 252, ${intensity * 0.35})`;
          ctx.beginPath();
          ctx.arc(x, y, 1.25 + intensity * 0.75, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      const beamY = (Math.sin(time * 0.4) * 0.5 + 0.5) * h;
      const beamGrad = ctx.createLinearGradient(0, beamY - 40, 0, beamY + 40);
      beamGrad.addColorStop(0, "rgba(129, 140, 248, 0)");
      beamGrad.addColorStop(0.5, "rgba(129, 140, 248, 0.08)");
      beamGrad.addColorStop(1, "rgba(129, 140, 248, 0)");
      ctx.fillStyle = beamGrad;
      ctx.fillRect(0, beamY - 40, w, 80);

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, []);

  return <canvas ref={canvasRef} className="block h-full w-full" />;
}
