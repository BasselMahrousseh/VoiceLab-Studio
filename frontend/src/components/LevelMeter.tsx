import { useEffect, useRef } from "react";
import { StudioRecorder } from "../audio/recorder";

/** Live input meter with dBFS scale, peak hold and sticky clip light. */
export default function LevelMeter({ recorder, active }: { recorder: StudioRecorder | null; active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const peakHold = useRef(0);
  const clipUntil = useRef(0);

  useEffect(() => {
    let raf = 0;
    const draw = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d")!;
      const { width: w, height: h } = canvas;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#11141a";
      ctx.fillRect(0, 0, w, h);

      const { rms, peak } = active && recorder?.ready ? recorder.level() : { rms: 0, peak: 0 };
      const now = performance.now();
      if (peak >= 0.999) clipUntil.current = now + 2000;
      peakHold.current = Math.max(peak, peakHold.current * 0.97);

      const toX = (v: number) => {
        const db = 20 * Math.log10(Math.max(v, 1e-5)); // -100..0
        return ((db + 60) / 60) * w; // show -60..0 dBFS
      };

      // gradient bar for RMS
      const grad = ctx.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, "#2f9e77");
      grad.addColorStop(0.75, "#e8c34a");
      grad.addColorStop(0.92, "#e5484d");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 4, Math.max(0, toX(rms)), h - 8);

      // peak hold line
      ctx.fillStyle = "#e8eaed";
      ctx.fillRect(Math.max(0, toX(peakHold.current)) - 1, 2, 2, h - 4);

      // scale ticks
      ctx.fillStyle = "#3a4250";
      for (const db of [-50, -40, -30, -20, -12, -6, -3]) {
        const x = ((db + 60) / 60) * w;
        ctx.fillRect(x, 0, 1, h);
      }

      // clip light
      if (now < clipUntil.current) {
        ctx.fillStyle = "#e5484d";
        ctx.beginPath();
        ctx.arc(w - 10, h / 2, 5, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [recorder, active]);

  return <canvas ref={canvasRef} width={560} height={22} className="level-meter" />;
}
