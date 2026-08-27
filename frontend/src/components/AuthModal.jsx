import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export default function AuthModal() {
  const {
    modalOpen,
    modalMode,
    setModalMode,
    closeModal,
    login,
    register,
    verifyEmail,
    resendOtp,
    forgotPassword,
    resetPassword,
    pendingEmail,
  } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!modalOpen) return null;

  const reset = () => {
    setEmail('');
    setPassword('');
    setName('');
    setOtp('');
    setNewPassword('');
    setConfirmPassword('');
    setError('');
    setInfo('');
  };

  const handleClose = () => {
    reset();
    closeModal();
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) handleClose();
  };

  const switchMode = (mode) => {
    setError('');
    setInfo('');
    setModalMode(mode);
  };

  const handleLoginOrRegister = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      if (modalMode === 'login') {
        await login(email.trim(), password);
      } else {
        await register(email.trim(), password, name.trim());
        setOtp('');
      }
    } catch (err) {
      if (!err.response?.data?.pendingVerification) {
        setError(err.response?.data?.error || 'Something went wrong. Please try again.');
      } else {
        setError(err.response.data.error);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerify = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await verifyEmail(pendingEmail, otp.trim());
      reset();
    } catch (err) {
      setError(err.response?.data?.error || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleResend = async () => {
    setError('');
    setInfo('');
    try {
      await resendOtp(pendingEmail);
      setInfo('A new code has been sent.');
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to resend code.');
    }
  };

  const handleForgot = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await forgotPassword(email.trim());
      setOtp('');
    } catch (err) {
      setError(err.response?.data?.error || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReset = async (e) => {
    e.preventDefault();
    setError('');
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(pendingEmail, otp.trim(), newPassword);
      reset();
    } catch (err) {
      setError(err.response?.data?.error || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const titles = {
    login: ['Welcome back', 'Log in to rate and review PGs.'],
    register: ['Create your account', 'Sign up to rate and review PGs.'],
    verify: ['Check your email', `We sent a 6-digit code to ${pendingEmail}.`],
    forgot: ['Forgot password?', "Enter your email and we'll send you a reset code."],
    reset: ['Reset your password', `Enter the code sent to ${pendingEmail} and a new password.`],
  };
  const [title, subtitle] = titles[modalMode];

  return (
    <div className="auth-modal-backdrop" onClick={handleBackdropClick}>
      <div className="auth-modal">
        <button className="auth-modal-close" onClick={handleClose}>✕</button>
        <h2 className="auth-modal-title">{title}</h2>
        <p className="auth-modal-subtitle">{subtitle}</p>

        {(modalMode === 'login' || modalMode === 'register') && (
          <form onSubmit={handleLoginOrRegister} className="auth-form">
            {modalMode === 'register' && (
              <input
                type="text"
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                minLength={2}
              />
            )}
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
            />
            {modalMode === 'login' && (
              <button
                type="button"
                className="auth-inline-link"
                onClick={() => switchMode('forgot')}
              >
                Forgot password?
              </button>
            )}
            {error && <div className="auth-error">{error}</div>}
            <button type="submit" className="auth-submit-btn" disabled={submitting}>
              {submitting ? '…' : modalMode === 'login' ? 'Log In' : 'Sign Up'}
            </button>
          </form>
        )}

        {modalMode === 'verify' && (
          <form onSubmit={handleVerify} className="auth-form">
            <input
              type="text"
              inputMode="numeric"
              placeholder="6-digit code"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
              required
              minLength={6}
              maxLength={6}
              className="auth-otp-input"
            />
            {info && <div className="auth-info">{info}</div>}
            {error && <div className="auth-error">{error}</div>}
            <button type="submit" className="auth-submit-btn" disabled={submitting || otp.length !== 6}>
              {submitting ? '…' : 'Verify & Continue'}
            </button>
            <button type="button" className="auth-inline-link" onClick={handleResend}>
              Resend code
            </button>
          </form>
        )}

        {modalMode === 'forgot' && (
          <form onSubmit={handleForgot} className="auth-form">
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            {error && <div className="auth-error">{error}</div>}
            <button type="submit" className="auth-submit-btn" disabled={submitting}>
              {submitting ? '…' : 'Send Reset Code'}
            </button>
          </form>
        )}

        {modalMode === 'reset' && (
          <form onSubmit={handleReset} className="auth-form">
            <input
              type="text"
              inputMode="numeric"
              placeholder="6-digit code"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
              required
              minLength={6}
              maxLength={6}
              className="auth-otp-input"
            />
            <input
              type="password"
              placeholder="New password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={6}
            />
            <input
              type="password"
              placeholder="Confirm new password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={6}
            />
            {error && <div className="auth-error">{error}</div>}
            <button type="submit" className="auth-submit-btn" disabled={submitting || otp.length !== 6}>
              {submitting ? '…' : 'Reset Password'}
            </button>
          </form>
        )}

        <div className="auth-switch">
          {modalMode === 'login' && (
            <>Don't have an account? <button className="auth-switch-btn" onClick={() => switchMode('register')}>Sign up</button></>
          )}
          {modalMode === 'register' && (
            <>Already have an account? <button className="auth-switch-btn" onClick={() => switchMode('login')}>Log in</button></>
          )}
          {(modalMode === 'verify' || modalMode === 'forgot' || modalMode === 'reset') && (
            <>Back to <button className="auth-switch-btn" onClick={() => switchMode('login')}>log in</button></>
          )}
        </div>
      </div>
    </div>
  );
}
