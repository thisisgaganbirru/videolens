"use client";

export default function CharcoalGlow() {
  return (
    <div className="relative h-full w-full bg-[#0b0c10]">
      <div className="absolute top-0 right-0 h-[40rem] w-[40rem] -translate-y-1/3 translate-x-1/3 rounded-full bg-purple-900/15 blur-[140px]" />
      <div className="absolute bottom-0 left-0 h-[45rem] w-[45rem] translate-y-1/3 -translate-x-1/3 rounded-full bg-indigo-900/15 blur-[150px]" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,rgba(0,0,0,0.4)_100%)]" />
    </div>
  );
}
