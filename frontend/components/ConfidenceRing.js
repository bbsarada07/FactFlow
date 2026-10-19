import { motion } from "framer-motion";
import CountUp from "react-countup";

export default function ConfidenceRing({ value, color, size = 80 }) {
  const stroke = 6;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const pct = value == null ? 0 : Math.round(value * 100);

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(255,255,255,0.07)" strokeWidth={stroke} fill="none" />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - pct / 100) }}
          transition={{ duration: 1.4, ease: [0.25, 0.46, 0.45, 0.94], delay: 0.3 }}
          style={{ filter: `drop-shadow(0 0 6px ${color})` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {value == null ? (
          <span className="mono text-[11px] text-secondary">—</span>
        ) : (
          <span className="font-display text-[20px] font-bold leading-none" style={{ color }}>
            <CountUp end={pct} duration={1.4} delay={0.3} />
            <span className="text-[11px]">%</span>
          </span>
        )}
        <span className="mono mt-1 text-[8px] tracking-[1.5px] text-secondary">CONFIDENCE</span>
      </div>
    </div>
  );
}
