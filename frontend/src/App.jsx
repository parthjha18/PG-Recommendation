import { useState } from 'react';
import api from './api';
import { useAuth } from './context/AuthContext';
import Hero from './components/Hero';
import PreferenceForm from './components/PreferenceForm';
import UserSummary from './components/UserSummary';
import StatsBar from './components/StatsBar';
import EmptyState from './components/EmptyState';
import PGCard from './components/PGCard';
import AuthModal from './components/AuthModal';
import WhatIfPanel from './components/WhatIfPanel';
import './App.css';

const DEFAULT_FORM = {
  location: '',
  destination: '',
  gender: '2',
  sharing: 'Any',
  meals: '2',
  wifi: false,
  ac: false,
  laundry: false,
  food: false,
};

// Single source of truth for "form state -> API payload", so a normal
// submit and an applied what-if suggestion always build the request the
// same way.
function toPayload(budget, form) {
  return {
    budget: Number(budget),
    location: form.location,
    destination: form.destination,
    gender: Number(form.gender),
    sharing: form.sharing,
    meals: Number(form.meals),
    wifi: form.wifi ? 1 : 0,
    ac: form.ac ? 1 : 0,
    laundry: form.laundry ? 1 : 0,
    food: form.food ? 1 : 0,
  };
}

export default function App() {
  const { user, logout, openModal } = useAuth();

  const [budget, setBudget] = useState(15000);
  const [form, setForm] = useState(DEFAULT_FORM);

  const [results, setResults] = useState(null);
  const [userPrefs, setUserPrefs] = useState(null);
  const [whatIf, setWhatIf] = useState(null);
  const [destinationInfo, setDestinationInfo] = useState(null);
  const [commuteError, setCommuteError] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const search = async (searchBudget, searchForm) => {
    const formData = toPayload(searchBudget, searchForm);

    setLoading(true);
    setError('');
    setResults(null);
    setWhatIf(null);
    setDestinationInfo(null);
    setCommuteError('');
    setUserPrefs(formData);
    setSubmitted(true);

    try {
      const { data } = await api.post('/recommendations', formData);
      setWhatIf(data.what_if || null);
      setDestinationInfo(data.destination || null);
      setCommuteError(data.commute_error || '');
      if (data.error) {
        setError(data.error);
        setResults(null);
      } else {
        setResults(data.results || []);
      }
    } catch (err) {
      if (err.response?.status === 503) {
        setError('ML service is not available. Please ensure the recommendation engine is running.');
      } else {
        setError('Something went wrong. Please try again.');
      }
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const handleFormSubmit = (e) => {
    e.preventDefault();
    search(budget, form);
  };

  const handleFieldChange = (name, value) => {
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  // A "Try this →" click on a what-if suggestion merges its change into the
  // CURRENT form state, updates the visible controls, and re-runs the
  // search with the merged values — all synchronously in this one handler,
  // so there's no risk of submitting against stale state.
  const handleApplyWhatIf = (change) => {
    const newBudget = change.budget !== undefined ? change.budget : budget;
    const newForm = { ...form };
    if (change.sharing !== undefined) newForm.sharing = change.sharing;
    if (change.location !== undefined) newForm.location = change.location;
    if (change.meals !== undefined) newForm.meals = String(change.meals);
    if (change.wifi !== undefined) newForm.wifi = !!change.wifi;
    if (change.ac !== undefined) newForm.ac = !!change.ac;
    if (change.laundry !== undefined) newForm.laundry = !!change.laundry;
    if (change.food !== undefined) newForm.food = !!change.food;

    setBudget(newBudget);
    setForm(newForm);
    search(newBudget, newForm);
  };

  return (
    <>
      <div className="blob blob-1" />
      <div className="blob blob-2" />
      <div className="blob blob-3" />

      <div className="page-wrap">
        <div className="auth-bar">
          {user ? (
            <div className="auth-user-chip">
              👋 {user.name}
              <button className="auth-logout-btn" onClick={logout}>Log out</button>
            </div>
          ) : (
            <button className="auth-login-btn" onClick={() => openModal('login')}>Log In / Sign Up</button>
          )}
        </div>

        <Hero />

        <PreferenceForm
          budget={budget}
          form={form}
          onBudgetChange={setBudget}
          onFieldChange={handleFieldChange}
          onSubmit={handleFormSubmit}
          loading={loading}
        />

        {results && results.length > 0 && <UserSummary user={userPrefs} />}

        {destinationInfo && results && results.length > 0 && (
          <div className="commute-banner">
            🚗 Ranked by real commute time to <strong>{destinationInfo.display_name.split(',')[0]}</strong>
          </div>
        )}

        {commuteError && (
          <div className="commute-banner warn">⚠️ {commuteError}</div>
        )}

        {results && results.length > 0 && <StatsBar results={results} />}

        {results && results.length > 0 && (
          <div className="results-header">
            <span>Your Recommendations</span>
            <span className="results-count">{results.length} found</span>
          </div>
        )}

        {results && results.length > 0 && (
          <div className="results-grid">
            {results.map((pg) => (
              <PGCard key={pg.PG_ID || pg.Rank} pg={pg} />
            ))}
          </div>
        )}

        {(error || (submitted && results && results.length === 0)) && (
          <EmptyState error={error} />
        )}

        {submitted && !loading && (
          <WhatIfPanel suggestions={whatIf} onApply={handleApplyWhatIf} applying={loading} />
        )}

        <footer>
          PG Finder · Bangalore North · Built with ❤️ for smarter house-hunting
        </footer>
      </div>

      <AuthModal />
    </>
  );
}
