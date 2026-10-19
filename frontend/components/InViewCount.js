import { useInView } from "framer-motion";
import { useRef } from "react";
import CountUp from "react-countup";

/** CountUp that starts the first time it scrolls into view. */
export default function InViewCount({ end, decimals = 0, duration = 2, separator = "," }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  return (
    <span ref={ref}>
      {inView ? <CountUp end={end} decimals={decimals} duration={duration} separator={separator} /> : (0).toFixed(decimals)}
    </span>
  );
}
