export default function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="#140507" stroke="#FF2D2D" strokeOpacity="0.5" />
      <path d="M9 23V9h2.6l8 9.6V9H23v14h-2.6l-8-9.6V23H9z" fill="#FF2D2D" />
      <path d="M9 23V9h2.6l8 9.6" stroke="#FF6B6B" strokeWidth="0.6" strokeOpacity="0.6" />
    </svg>
  );
}
