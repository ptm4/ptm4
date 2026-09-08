// Full-bleed Dozzle iframe. Same-origin via nginx /dozzle (mixed-content — the
// dashboard is https, dozzle is http); DOZZLE_BASE=/dozzle on the container side.
export default function LogsPage() {
  return (
    <div className="logs-page glass">
      <iframe src="/dozzle/" title="Dozzle — container logs" />
    </div>
  );
}
