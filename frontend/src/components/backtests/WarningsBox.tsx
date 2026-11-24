export default function WarningsBox({ warnings }: { warnings: string[] }) {
  return (
    <section className="mb-4 rounded-card border border-warning/60 bg-warning/10 px-4 py-3" role="region" aria-label="Warnings">
      <strong>Read this before trusting the result</strong>
      {warnings.length === 0 ? (
        <p className="muted">No warnings yet. The warnings appear once the test finishes.</p>
      ) : (
        <ul>
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
