"use client";

import { useEffect, useRef } from "react";

export default function CosmicNebula() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let time = 0;

    const starCount = 120;
    const stars: { x: number; y: number; r: number; alpha: number }[] = [];
    for (let i = 0; i < starCount; i++) {
      stars.push({
        x: Math.random(),
        y: Math.random(),
        r: Math.random() * 1.4 + 0.3,
        alpha: Math.random() * 0.8 + 0.2,
      });
    }

    const render = () => {
      time += 0.008;
      const w = (canvas.width = canvas.clientWidth);
      const h = (canvas.height = canvas.clientHeight);

      ctx.fillStyle = "#05060b";
      ctx.fillRect(0, 0, w, h);

      const nx1 = w * (0.3 + Math.sin(time) * 0.15);
      const ny1 = h * (0.35 + Math.cos(time * 0.8) * 0.15);
      const grad1 = ctx.createRadialGradient(nx1, ny1, 20, nx1, ny1, w * 0.5);
      grad1.addColorStop(0, "rgba(139, 92, 246, 0.25)");
      grad1.addColorStop(0.6, "rgba(67, 56, 202, 0.1)");
      grad1.addColorStop(1, "rgba(5, 6, 11, 0)");
      ctx.fillStyle = grad1;
      ctx.fillRect(0, 0, w, h);

      const nx2 = w * (0.7 + Math.cos(time * 0.7) * 0.15);
      const ny2 = h * (0.65 + Math.sin(time * 0.9) * 0.15);
      const grad2 = ctx.createRadialGradient(nx2, ny2, 20, nx2, ny2, w * 0.45);
      grad2.addColorStop(0, "rgba(236, 72, 153, 0.18)");
      grad2.addColorStop(0.5, "rgba(124, 58, 237, 0.08)");
      grad2.addColorStop(1, "rgba(5, 6, 11, 0)");
      ctx.fillStyle = grad2;
      ctx.fillRect(0, 0, w, h);

      for (const s of stars) {
        const sx = s.x * w;
        const sy = s.y * h;
        const twinkle = Math.sin(time * 3 + s.x * 100) * 0.3 + 0.7;
        ctx.fillStyle = `rgba(224, 231, 255, ${s.alpha * twinkle * 0.75})`;
        ctx.beginPath();
        ctx.arc(sx, sy, s.r, 0, Math.PI * 2);
        ctx.fill();
      }

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, []);

  return <canvas ref={canvasRef} className="block h-full w-full" />;
}
