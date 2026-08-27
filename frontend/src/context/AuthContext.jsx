import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import api from '../api';

const TOKEN_KEY = 'pg_auth_token';
const AuthContext = createContext(null);

// modalMode: 'login' | 'register' | 'verify' | 'forgot' | 'reset'
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState('login');
  const [pendingEmail, setPendingEmail] = useState('');

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setReady(true);
      return;
    }
    api
      .get('/auth/me')
      .then(({ data }) => setUser(data.user))
      .catch(() => localStorage.removeItem(TOKEN_KEY))
      .finally(() => setReady(true));
  }, []);

  const applySession = (data) => {
    localStorage.setItem(TOKEN_KEY, data.token);
    setUser(data.user);
    setModalOpen(false);
  };

  const login = useCallback(async (email, password) => {
    try {
      const { data } = await api.post('/auth/login', { email, password });
      applySession(data);
      return data.user;
    } catch (err) {
      if (err.response?.data?.pendingVerification) {
        setPendingEmail(err.response.data.email);
        setModalMode('verify');
      }
      throw err;
    }
  }, []);

  const register = useCallback(async (email, password, name) => {
    const { data } = await api.post('/auth/register', { email, password, name });
    setPendingEmail(data.email);
    setModalMode('verify');
    return data;
  }, []);

  const verifyEmail = useCallback(async (email, otp) => {
    const { data } = await api.post('/auth/verify-email', { email, otp });
    applySession(data);
    return data.user;
  }, []);

  const resendOtp = useCallback(async (email) => {
    const { data } = await api.post('/auth/resend-otp', { email });
    return data;
  }, []);

  const forgotPassword = useCallback(async (email) => {
    const { data } = await api.post('/auth/forgot-password', { email });
    setPendingEmail(email);
    setModalMode('reset');
    return data;
  }, []);

  const resetPassword = useCallback(async (email, otp, newPassword) => {
    const { data } = await api.post('/auth/reset-password', { email, otp, new_password: newPassword });
    applySession(data);
    return data.user;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
  }, []);

  // Call before a protected action. Returns true if already logged in;
  // otherwise opens the login modal and returns false.
  const requireAuth = useCallback(
    (mode = 'login') => {
      if (user) return true;
      setModalMode(mode);
      setModalOpen(true);
      return false;
    },
    [user]
  );

  return (
    <AuthContext.Provider
      value={{
        user,
        ready,
        login,
        register,
        verifyEmail,
        resendOtp,
        forgotPassword,
        resetPassword,
        logout,
        requireAuth,
        modalOpen,
        modalMode,
        setModalMode,
        pendingEmail,
        setPendingEmail,
        openModal: (mode = 'login') => {
          setModalMode(mode);
          setModalOpen(true);
        },
        closeModal: () => setModalOpen(false),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
