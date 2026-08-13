"use client";

import { useEffect, useRef } from "react";

export default function DigitalMatrix() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    const fontSize = 14;
    let columns = Math.floor(canvas.clientWidth / fontSize);
    let drops: number[] = Array(columns).fill(1);

    const charSet = "0123456789ABCDEFｦｱｳｴｵｶｷｹｺｻｼｽｾｿﾀﾂﾃﾅﾆﾇﾈﾊﾋﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜ".split("");

    const render = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        columns = Math.floor(w / fontSize);
        drops = Array(columns).fill(1);
      }

      ctx.fillStyle = "rgba(4, 8, 12, 0.12)";
      ctx.fillRect(0, 0, w, h);

      ctx.fillStyle = "#10b981";
      ctx.font = `${fontSize}px monospace`;

      for (let i = 0; i < drops.length; i++) {
        const text = charSet[Math.floor(Math.random() * charSet.length)];
        const x = i * fontSize;
        const y = drops[i] * fontSize;

        if (Math.random() > 0.85) {
          ctx.fillStyle = "#a7f3d0";
        } else {
          ctx.fillStyle = "#059669";
        }

        ctx.fillText(text, x, y);

        if (y > h && Math.random() > 0.975) {
          drops[i] = 0;
        }
        drops[i]++;
      }

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, []);

  return <canvas ref={canvasRef} className="block h-full w-full" />;
}
