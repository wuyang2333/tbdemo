import { StrategyWorkspacePage } from "./strategy-workspace-page";

export function ContentPage({ sectionId }: { sectionId: string }) {
  return <StrategyWorkspacePage sectionId={sectionId || "content-overview"} />;
}
