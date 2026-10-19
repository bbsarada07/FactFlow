export const VERDICTS = {
  FALSE: {
    label: "FALSE",
    color: "#FF2D2D",
    text: "#fff",
    gradient: "linear-gradient(135deg, rgba(255,45,45,0.15), transparent)",
    soft: "rgba(255,45,45,0.12)",
  },
  TRUE: {
    label: "TRUE",
    color: "#00E676",
    text: "#04140b",
    gradient: "linear-gradient(135deg, rgba(0,230,118,0.12), transparent)",
    soft: "rgba(0,230,118,0.12)",
  },
  MISLEADING: {
    label: "MISLEADING",
    color: "#FF6B00",
    text: "#fff",
    gradient: "linear-gradient(135deg, rgba(255,107,0,0.12), transparent)",
    soft: "rgba(255,107,0,0.12)",
  },
  UNVERIFIED: {
    label: "UNVERIFIED",
    color: "#8888A0",
    text: "#fff",
    gradient: "linear-gradient(135deg, rgba(136,136,160,0.08), transparent)",
    soft: "rgba(136,136,160,0.12)",
  },
  SATIRE: {
    label: "SATIRE",
    color: "#B04FD0",
    text: "#fff",
    gradient: "linear-gradient(135deg, rgba(156,39,176,0.12), transparent)",
    soft: "rgba(156,39,176,0.14)",
  },
};

export const verdictStyle = (v) => VERDICTS[v] || VERDICTS.UNVERIFIED;

export const HARM_COLORS = {
  VIOLENCE: "#FF2D2D",
  HEALTH: "#FF6B00",
  COMMUNAL: "#B04FD0",
  ELECTORAL: "#2979FF",
  FINANCIAL: "#E8B400",
  REPUTATIONAL: "#00B8D4",
  NONE: "#8888A0",
};

export const LEVEL_COLORS = {
  CRITICAL: "#FF2D2D",
  HIGH: "#FF6B00",
  MEDIUM: "#E8B400",
  LOW: "#00E676",
};

export const TIER_COLORS = { 1: "#00E676", 2: "#2979FF", 3: "#FF6B00", 4: "#FF2D2D" };

export const PLATFORM_ICONS = {
  whatsapp: "📱",
  twitter: "🐦",
  x: "🐦",
  instagram: "📸",
  facebook: "📘",
  youtube: "▶️",
  news: "📰",
  extension: "🧩",
  web: "🌐",
};

export const platformIcon = (p) => PLATFORM_ICONS[(p || "web").toLowerCase()] || "🌐";

export const LANGUAGES = [
  { code: "auto", label: "Auto" },
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "mr", label: "मराठी" },
  { code: "bn", label: "বাংলা" },
  { code: "ta", label: "தமிழ்" },
  { code: "te", label: "తెలుగు" },
  { code: "gu", label: "ગુજરાતી" },
  { code: "kn", label: "ಕನ್ನಡ" },
  { code: "ml", label: "മലയാളം" },
  { code: "pa", label: "ਪੰਜਾਬੀ" },
  { code: "ur", label: "اردو" },
];

export const EASE = [0.25, 0.46, 0.45, 0.94];

export function timeAgo(iso) {
  if (!iso) return "";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 45) return "just now";
  const units = [
    ["y", 31536000],
    ["mo", 2592000],
    ["d", 86400],
    ["h", 3600],
    ["m", 60],
  ];
  for (const [label, size] of units) {
    if (secs >= size) return `${Math.floor(secs / size)}${label} ago`;
  }
  return "1m ago";
}

export function formatClock(ms) {
  const total = Math.floor((ms || 0) / 1000);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export function formatDate(iso) {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
