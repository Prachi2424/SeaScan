interface StatusDotProps {
  status: "online" | "offline" | "checking";
}

export function StatusDot({ status }: StatusDotProps) {
  return <span aria-label={`Backend ${status}`} className={`status-dot status-dot--${status}`} />;
}
