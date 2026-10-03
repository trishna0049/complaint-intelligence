/** Diverging sentiment palette: red arm ↔ neutral gray ↔ blue arm (lightness monotonic per arm). */
export const SENTIMENT_COLORS: Record<string, string> = {
  "Very Negative": "#c42f30",
  Negative: "#ee8f8b",
  Neutral: "#bdbcb5",
  Positive: "#86b6ef",
  "Very Positive": "#2a78d6",
};
export const SENTIMENTS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"] as const;
