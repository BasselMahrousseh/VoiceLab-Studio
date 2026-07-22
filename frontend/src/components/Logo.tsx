/** e& brand mark — the official logo shipped in `frontend/public/logo.png`. */
export default function Logo({
  height = 30,
  className = "",
}: {
  height?: number;
  className?: string;
}) {
  return (
    <img
      src="/logo.png"
      height={height}
      alt="e&"
      className={className}
      style={{ height, width: "auto", display: "block" }}
    />
  );
}
