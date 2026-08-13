"use client";

import { useEffect, useRef } from "react";

const CHROMA_VERTEX = `
attribute vec2 a_position;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const CHROMA_FRAGMENT = `
precision highp float;
uniform vec2 u_resolution;
uniform float u_time;

float wave(vec2 p, float t) {
  return sin(p.x * 2.8 + t * 0.9) * cos(p.y * 2.5 + t * 0.7) * 0.5
       + sin(p.y * 4.2 - t * 1.1 + p.x * 1.8) * 0.3
       + sin(length(p * 1.8) - t * 1.5) * 0.2;
}

vec3 palette(float t) {
  vec3 a = vec3(0.4, 0.4, 0.5);
  vec3 b = vec3(0.5, 0.5, 0.5);
  vec3 c = vec3(1.0, 1.0, 1.0);
  vec3 d = vec3(0.00, 0.33, 0.67);
  return a + b * cos(6.28318 * (c * t + d));
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution.xy;
  float aspect = u_resolution.x / max(u_resolution.y, 1.0);
  vec2 st = (uv - 0.5) * vec2(aspect, 1.0) * 2.2;

  float t = u_time * 0.35;
  float height = wave(st, t);

  vec2 eps = vec2(0.015, 0.0);
  float hx = wave(st + eps.xy, t) - wave(st - eps.xy, t);
  float hy = wave(st + eps.yx, t) - wave(st - eps.yx, t);
  vec3 normal = normalize(vec3(-hx * 3.5, -hy * 3.5, 1.0));

  vec3 lightDir = normalize(vec3(0.4, 0.7, 0.9));
  float diff = max(dot(normal, lightDir), 0.0);
  vec3 viewDir = vec3(0.0, 0.0, 1.0);
  vec3 halfDir = normalize(lightDir + viewDir);
  float spec = pow(max(dot(normal, halfDir), 0.0), 28.0);

  float fresnel = pow(1.0 - max(dot(normal, viewDir), 0.0), 2.5);
  vec3 chroma = palette(height * 0.6 + fresnel * 0.7 + t * 0.04);

  vec3 baseDark = vec3(0.02, 0.03, 0.07);
  vec3 finalColor = mix(baseDark, chroma, 0.6 + diff * 0.3) + spec * vec3(0.85, 0.92, 1.0) * 0.6;

  float dist = length(uv - vec2(0.5, 0.5));
  finalColor *= (1.0 - dist * 0.35);

  gl_FragColor = vec4(finalColor, 1.0);
}
`;

export default function LiquidChroma() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl", { alpha: false, powerPreference: "low-power" });
    if (!gl) return;

    const createShader = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };

    const vert = createShader(gl.VERTEX_SHADER, CHROMA_VERTEX);
    const frag = createShader(gl.FRAGMENT_SHADER, CHROMA_FRAGMENT);
    const prog = gl.createProgram()!;
    gl.attachShader(prog, vert);
    gl.attachShader(prog, frag);
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);

    const pos = gl.getAttribLocation(prog, "a_position");
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

    const resLoc = gl.getUniformLocation(prog, "u_resolution");
    const timeLoc = gl.getUniformLocation(prog, "u_time");

    let animId: number;
    const start = performance.now();

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
        gl.uniform2f(resLoc, w, h);
      }
    };

    const render = (now: number) => {
      resize();
      gl.uniform1f(timeLoc, (now - start) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animId);
      gl.deleteBuffer(buf);
      gl.deleteProgram(prog);
      gl.deleteShader(vert);
      gl.deleteShader(frag);
    };
  }, []);

  return <canvas ref={canvasRef} className="block h-full w-full" />;
}
