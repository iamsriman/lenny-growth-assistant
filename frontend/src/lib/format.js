export function relativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Math.max(0, Date.now() - then);
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function skillLabel(skill) {
  return (
    {
      grounded_answer: "Answer",
      ship30_essay: "Ship 30 essay",
      artifact: "Artifact",
    }[skill] || skill || ""
  );
}

export function stageLabel(stage, data = {}) {
  return (
    {
      routing: "Choosing a skill",
      retrieving: "Searching transcripts",
      generating: data.note || "Writing",
      critiquing: "Checking against the Ship 30 rules",
      revising: data.note ? `Revising — ${data.note}` : "Revising",
    }[stage] || stage
  );
}
