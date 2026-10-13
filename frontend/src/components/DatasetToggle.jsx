// Switches the whole search between the generated demo dataset and the PGs
// collected through the Google Form. Counts come from the ML service, so the
// label always says exactly what is loaded.
export default function DatasetToggle({ value, onChange, info, disabled, onRefresh, refreshing, refreshNote }) {
  const demo = info?.demo;
  const real = info?.real;
  const realLoaded = !!real?.loaded;

  return (
    <div className="dataset-toggle" role="group" aria-label="Dataset">
      <span className="dataset-toggle-label">Data source</span>
      <button
        type="button"
        className={`dataset-opt ${value === 'demo' ? 'active' : ''}`}
        onClick={() => onChange('demo')}
        disabled={disabled}
      >
        Demo data
        <span className="dataset-count">
          {demo?.loaded ? `${demo.pgs.toLocaleString('en-IN')} generated PGs` : 'generated'}
        </span>
      </button>
      <button
        type="button"
        className={`dataset-opt ${value === 'real' ? 'active' : ''}`}
        onClick={() => onChange('real')}
        disabled={disabled}
        title={realLoaded ? 'PGs collected from residents via the Google Form' : 'No real PG data imported yet'}
      >
        Real data
        <span className="dataset-count">
          {realLoaded ? `${real.pgs} collected PG${real.pgs === 1 ? '' : 's'}` : 'none imported yet'}
        </span>
      </button>
      {real?.sync_available && (
        <button
          type="button"
          className="dataset-refresh"
          onClick={onRefresh}
          disabled={disabled || refreshing}
          title="Fetch the latest form responses from the Google Sheet"
        >
          {refreshing ? '⟳ Refreshing…' : '↻ Refresh'}
        </button>
      )}
      {refreshNote && (
        <span className={`dataset-note ${refreshNote.error ? 'error' : ''}`}>{refreshNote.text}</span>
      )}
    </div>
  );
}
