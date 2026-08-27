export const BRAND = {
  productName: "知枢 Nexus",
  chineseName: "知枢",
  assistantName: "知枢 AI",
  workspaceName: "知枢工作台",
  workspaceSubtitle: "企业智能工作台",
  positioning: "连接企业知识、经营数据与智能工具的工作台",
} as const;

export type BrandMarkSize = "regular" | "large";

export function BrandMark({
  size = "regular",
  decorative = false,
  className = "",
}: {
  size?: BrandMarkSize;
  decorative?: boolean;
  className?: string;
}) {
  const classes = ["brand-mark", size === "large" ? "large" : "", className]
    .filter(Boolean)
    .join(" ");
  const label = decorative ? undefined : "知枢 AI 助手";
  return (
    <span className={classes} aria-label={label} aria-hidden={decorative || undefined}>
      <span>知枢</span>
    </span>
  );
}

export function BrandLockup({
  compact = false,
  className = "",
}: {
  compact?: boolean;
  className?: string;
}) {
  return (
    <span className={["brand-lockup", compact ? "compact" : "", className].filter(Boolean).join(" ")}>
      <BrandMark decorative />
      <span>
        <strong>{BRAND.productName}</strong>
        <small>{BRAND.workspaceSubtitle}</small>
      </span>
    </span>
  );
}
