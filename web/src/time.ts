/** "just now", "15m ago", "3h ago", "3d ago", then a short date. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = (now.getTime() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
