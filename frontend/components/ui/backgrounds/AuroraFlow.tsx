"use client";

import { useEffect, useRef } from "react";

const AURORA_VERTEX = `
attribute vec2 a_position;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const AURORA_FRAGMENT = `
precision highp float;
uniform vec2 u_resolution;
uniform float u_time;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
    mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
    u.y
  );
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  mat2 rot = mat2(0.8, -0.6, 0.6, 0.8);
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = rot * p * 2.02 + vec2(1.7, 9.2);
    a *= 0.5;
  }
  return v;
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution.xy;
  float aspect = u_resolution.x / max(u_resolution.y, 1.0);
  vec2 st = vec2(uv.x * aspect, uv.y);
  float t = u_time * 0.15;

  vec2 q = vec2(fbm(st + vec2(t * 0.2, t * 0.1)), fbm(st + vec2(-t * 0.15, t * 0.25)));
  vec2 r = vec2(fbm(st + 4.0 * q + vec2(t * 0.3, -t * 0.2)), fbm(st + 4.0 * q + vec2(-t * 0.2, t * 0.1)));

  float f = fbm(st + 4.0 * r);

  vec3 deepBg = vec3(0.04, 0.05, 0.09);
  vec3 violetGlow = vec3(0.38, 0.14, 0.62);
  vec3 cyanHighlight = vec3(0.05, 0.52, 0.68);
  vec3 emeraldGlow = vec3(0.12, 0.58, 0.42);

  vec3 color = mix(deepBg, violetGlow, clamp(f * f * 3.2, 0.0, 1.0));
  color = mix(color, cyanHighlight, clamp(length(q.x), 0.0, 1.0) * 0.65);
  color = mix(color, emeraldGlow, clamp(r.y * r.y, 0.0, 1.0) * 0.45);

  float dist = length(uv - vec2(0.5, 0.5));
  color *= (1.0 - dist * 0.45);
  color += (hash(gl_FragCoord.xy + u_time) - 0.5) * 0.015;

  gl_FragColor = vec4(color, 1.0);
}
`;

export default function AuroraFlow() {
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

    const vert = createShader(gl.VERTEX_SHADER, AURORA_VERTEX);
    const frag = createShader(gl.FRAGMENT_SHADER, AURORA_FRAGMENT);
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
