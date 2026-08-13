"use client";

export default function GlassOrbs() {
  return (
    <div className="relative h-full w-full overflow-hidden bg-[#0a0a10]">
      <div
        className="absolute top-[-10%] left-[15%] h-[35rem] w-[35rem] rounded-full bg-gradient-to-tr from-purple-600/40 via-indigo-600/30 to-violet-500/20 blur-[100px]"
        style={{ animation: "floatOrb1 18s ease-in-out infinite alternate" }}
      />
      <div
        className="absolute top-[40%] right-[10%] h-[32rem] w-[32rem] rounded-full bg-gradient-to-br from-cyan-500/30 via-teal-600/25 to-blue-600/20 blur-[110px]"
        style={{ animation: "floatOrb2 22s ease-in-out infinite alternate" }}
      />
      <div
        className="absolute bottom-[-10%] left-[30%] h-[38rem] w-[38rem] rounded-full bg-gradient-to-r from-fuchsia-600/30 via-pink-600/20 to-purple-800/30 blur-[120px]"
        style={{ animation: "floatOrb3 25s ease-in-out infinite alternate" }}
      />
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `radial-gradient(#ffffff 1px, transparent 1px)`,
          backgroundSize: "28px 28px",
        }}
      />
      <style jsx>{`
        @keyframes floatOrb1 {
          0% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(80px, 60px) scale(1.1); }
          100% { transform: translate(-60px, 100px) scale(0.95); }
        }
        @keyframes floatOrb2 {
          0% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(-90px, -70px) scale(1.15); }
          100% { transform: translate(50px, -110px) scale(0.9); }
        }
        @keyframes floatOrb3 {
          0% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(110px, -80px) scale(1.05); }
          100% { transform: translate(-70px, -40px) scale(1.1); }
        }
      `}</style>
    </div>
  );
}
