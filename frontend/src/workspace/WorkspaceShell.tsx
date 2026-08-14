import type { ReactNode } from "react";

export default function WorkspaceShell({
  rail,
  header,
  thread,
  composer,
  inspector,
  inspectorOpen,
}: {
  rail: ReactNode;
  header: ReactNode;
  thread: ReactNode;
  composer: ReactNode;
  inspector: ReactNode;
  inspectorOpen: boolean;
}) {
  return (
    <div className={`enterprise-workspace ${inspectorOpen ? "inspector-visible" : "inspector-hidden"}`}>
      {rail}
      <section className="conversation-workspace">
        {header}
        <div className="conversation-stage" id="main-content" tabIndex={-1}>
          {thread}
        </div>
        {composer}
      </section>
      {inspector}
    </div>
  );
}
