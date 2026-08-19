/** Full e& Lahja Studio brand lockup. */
export default function Logo({
  height = 54,
  className = "",
}: {
  height?: number;
  className?: string;
}) {
  return (
    <img
      src="/lahja-studio-logo.png"
      height={height}
      alt="e& Lahja Studio"
      className={className}
      style={{ height, width: "auto", maxWidth: "100%", objectFit: "contain", display: "block" }}
    />
  );
}
