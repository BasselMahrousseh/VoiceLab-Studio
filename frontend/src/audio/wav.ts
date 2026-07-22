/** Encode Float32 PCM as a WAV file (IEEE float, format 3).
 * The master keeps full float precision; the backend derives PCM-16 exports.
 */
export function encodeWavFloat32(samples: Float32Array, sampleRate: number): Blob {
  const dataSize = samples.length * 4;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  let p = 0;
  const str = (s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(p++, s.charCodeAt(i));
  };
  const u32 = (v: number) => {
    view.setUint32(p, v, true);
    p += 4;
  };
  const u16 = (v: number) => {
    view.setUint16(p, v, true);
    p += 2;
  };

  str("RIFF");
  u32(36 + dataSize);
  str("WAVE");
  str("fmt ");
  u32(16); // fmt chunk size
  u16(3); // IEEE float
  u16(1); // mono
  u32(sampleRate);
  u32(sampleRate * 4); // byte rate
  u16(4); // block align
  u16(32); // bits per sample
  str("data");
  u32(dataSize);
  new Float32Array(buffer, 44).set(samples);
  return new Blob([buffer], { type: "audio/wav" });
}
