// Placeholder for pages that land in a later phase. Every stub page still renders
// inside the finished shell, so navigation, theme and glass are testable end to end
// before the page content exists.
export function PageStub({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="page-stub glass card">
      <div>
        <h2>{title}</h2>
        <p>This page is being rebuilt for the v2 redesign.<br />
          Until it lands, everything still works in the <a href="/legacy/">legacy UI</a>.</p>
        <span className="phase">{phase}</span>
      </div>
    </div>
  );
}
