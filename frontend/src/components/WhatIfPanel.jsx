const LEVER_ICON = {
  budget: '💰',
  sharing: '🛏️',
  location: '📍',
  amenity: '🧩',
};

export default function WhatIfPanel({ suggestions, onApply, applying }) {
  if (!suggestions || suggestions.length === 0) return null;

  return (
    <div className="whatif-panel">
      <div className="whatif-title">
        💡 What if…
        <span className="whatif-subtitle">Small changes that would actually change your results</span>
      </div>
      <div className="whatif-cards">
        {suggestions.map((s, i) => (
          <div className="whatif-card" key={`${s.lever}-${i}`}>
            <div className="whatif-icon">{LEVER_ICON[s.lever] || '✨'}</div>
            <div className="whatif-body">
              <div className="whatif-headline">{s.headline}</div>
              <div className="whatif-detail">{s.detail}</div>
            </div>
            <button
              className="whatif-apply-btn"
              disabled={applying}
              onClick={() => onApply(s.change)}
            >
              Try this →
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
