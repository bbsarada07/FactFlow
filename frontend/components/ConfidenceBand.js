import { motion } from "framer-motion";

const LEVELS = ["low", "medium", "high"];

/** Three-step confidence meter. Shows the band only; raw numbers live in the details view. */
export default function ConfidenceBand({ band = "low", color, archive = false }) {
  const filled = LEVELS.indexOf(band) + 1;

  return (
    <div className="flex shrink-0 flex-col items-end gap-2" aria-label={archive ? "Archived verdict" : `${band} confidence`}>
      <div className="flex gap-1.5">
        {LEVELS.map((l, i) => (
          <motion.span
            key={l}
            className="h-2 w-7 rounded-full sm:w-9"
            initial={{ opacity: 0.2, scaleX: 0.4 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{ delay: 0.3 + i * 0.12, duration: 0.4 }}
            style={{
              background: !archive && i < filled ? color : "rgba(255,255,255,0.08)",
              boxShadow: !archive && i < filled ? `0 0 10px ${color}66` : "none",
            }}
          />
        ))}
      </div>
      <span className="mono text-[10.5px] tracking-[2px] text-secondary">
        {archive ? "ARCHIVED RECORD" : `${band.toUpperCase()} CONFIDENCE`}
      </span>
    </div>
  );
}
