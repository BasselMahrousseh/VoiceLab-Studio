import { useEffect, useRef } from "react";

/** Static peak waveform of a captured take. */
export default function Waveform({ samples }: { samples: Float32Array }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;
    const { width: w, height: h } = canvas;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#11141a";
    ctx.fillRect(0, 0, w, h);
    if (!samples.length) return;

    const mid = h / 2;
    ctx.strokeStyle = "#2a313d";
    ctx.beginPath();
    ctx.moveTo(0, mid);
    ctx.lineTo(w, mid);
    ctx.stroke();

    const step = Math.max(1, Math.floor(samples.length / w));
    ctx.fillStyle = "#4fc3a1";
    for (let x = 0; x < w; x++) {
      let min = 1;
      let max = -1;
      const start = x * step;
      for (let i = start; i < Math.min(start + step, samples.length); i++) {
        const v = samples[i];
        if (v < min) min = v;
        if (v > max) max = v;
      }
      if (min > max) continue;
      const y1 = mid - max * (mid - 2);
      const y2 = mid - min * (mid - 2);
      ctx.fillRect(x, y1, 1, Math.max(1, y2 - y1));
    }
  }, [samples]);

  return <canvas ref={ref} width={860} height={110} className="waveform" />;
}
