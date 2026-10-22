export default function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="#140507" stroke="#FF2D2D" strokeOpacity="0.5" />
      <path d="M10.3 23V9h11.4v2.6h-8.8v3.5h7.2v2.6h-7.2V23h-2.6z" fill="#FF2D2D" />
      <path d="M10.3 23V9h11.4" stroke="#FF6B6B" strokeWidth="0.6" strokeOpacity="0.6" />
    </svg>
  );
}
