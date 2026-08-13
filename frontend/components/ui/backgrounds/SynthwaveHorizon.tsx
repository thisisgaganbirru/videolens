"use client";

import { useEffect, useRef } from "react";

export default function SynthwaveHorizon() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let offset = 0;

    const render = () => {
      offset = (offset + 0.8) % 40;
      const w = (canvas.width = canvas.clientWidth);
      const h = (canvas.height = canvas.clientHeight);

      const skyGrad = ctx.createLinearGradient(0, 0, 0, h * 0.65);
      skyGrad.addColorStop(0, "#080614");
      skyGrad.addColorStop(0.5, "#180a2a");
      skyGrad.addColorStop(1, "#3b0764");
      ctx.fillStyle = skyGrad;
      ctx.fillRect(0, 0, w, h * 0.65);

      const horizonY = h * 0.65;
      const sunRadius = Math.min(w, h) * 0.22;
      const sunGrad = ctx.createRadialGradient(w / 2, horizonY, 5, w / 2, horizonY, sunRadius);
      sunGrad.addColorStop(0, "#fde047");
      sunGrad.addColorStop(0.3, "#f97316");
      sunGrad.addColorStop(0.7, "#ec4899");
      sunGrad.addColorStop(1, "rgba(236, 72, 153, 0)");
      ctx.fillStyle = sunGrad;
      ctx.beginPath();
      ctx.arc(w / 2, horizonY, sunRadius, 0, Math.PI, true);
      ctx.fill();

      const groundGrad = ctx.createLinearGradient(0, horizonY, 0, h);
      groundGrad.addColorStop(0, "#0c0a1a");
      groundGrad.addColorStop(1, "#030206");
      ctx.fillStyle = groundGrad;
      ctx.fillRect(0, horizonY, w, h - horizonY);

      ctx.save();
      ctx.strokeStyle = "rgba(217, 70, 239, 0.35)";
      ctx.lineWidth = 1.2;

      ctx.beginPath();
      ctx.moveTo(0, horizonY);
      ctx.lineTo(w, horizonY);
      ctx.stroke();

      const lineCount = 28;
      for (let i = -lineCount; i <= lineCount; i++) {
        const x = (w / 2) + i * 45;
        ctx.beginPath();
        ctx.moveTo(w / 2, horizonY);
        ctx.lineTo(x * 2.2, h);
        ctx.stroke();
      }

      for (let y = horizonY + offset; y < h; y += Math.pow((y - horizonY) / 18, 1.4) + 6) {
        if (y < horizonY) continue;
        const alpha = Math.min(0.5, (y - horizonY) / 150);
        ctx.strokeStyle = `rgba(217, 70, 239, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      ctx.restore();

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, []);

  return <canvas ref={canvasRef} className="block h-full w-full" />;
}
