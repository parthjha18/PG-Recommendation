// backend/server.js — Express API Gateway
import 'dotenv/config';
import express from 'express';
import { PrismaClient } from './generated/prisma/client.ts';
import { PrismaPg } from '@prisma/adapter-pg';
import pg from 'pg';
import axios from 'axios';
import {
  hashPassword,
  comparePassword,
  signToken,
  requireAuth,
  generateOtp,
  hashOtp,
  compareOtp,
  otpExpiryDate,
} from './auth.js';
import { sendOtpEmail } from './mailer.js';

const app = express();

// Prisma adapter setup (see prisma.config.ts for datasource URL)
const pool = new pg.Pool({ connectionString: process.env.DATABASE_URL });
const adapter = new PrismaPg(pool);
const prisma = new PrismaClient({ adapter });

const PORT = process.env.PORT || 5005;
const ML_URL = process.env.ML_SERVICE_URL || 'http://localhost:8000';

// Manual CORS
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});

app.use(express.json());

// ── Helpers ──

async function getDbStats() {
  // Aggregate ratings: group by pg_id
  const ratingAgg = await prisma.rating.groupBy({
    by: ['pg_id'],
    _avg: { rating: true },
    _count: { rating: true },
  });
  const ratings = {};
  for (const r of ratingAgg) {
    ratings[r.pg_id] = {
      average_rating: r._avg.rating !== null ? parseFloat(r._avg.rating.toFixed(2)) : 3.5,
      rating_count: r._count.rating,
    };
  }

  // Aggregate reviews: group by pg_id
  const reviewAgg = await prisma.review.groupBy({
    by: ['pg_id'],
    _avg: { sentiment_score: true },
    _count: { sentiment_score: true },
  });
  const reviews = {};
  for (const r of reviewAgg) {
    reviews[r.pg_id] = {
      avg_sentiment: r._avg.sentiment_score !== null ? parseFloat(r._avg.sentiment_score.toFixed(4)) : 0.5,
      review_count: r._count.sentiment_score,
    };
  }

  return { ratings, reviews };
}

// ── POST /api/auth/register ── (creates an unverified account, emails an OTP)
app.post('/api/auth/register', async (req, res) => {
  try {
    const { email, password, name } = req.body;

    if (!email || !password || !name) {
      return res.status(400).json({ error: 'email, password, and name are required.' });
    }
    if (password.length < 6) {
      return res.status(422).json({ error: 'Password must be at least 6 characters.' });
    }

    const normalizedEmail = email.toLowerCase().trim();
    const existing = await prisma.user.findUnique({ where: { email: normalizedEmail } });
    if (existing && existing.email_verified) {
      return res.status(409).json({ error: 'An account with this email already exists.' });
    }

    const password_hash = await hashPassword(password);
    const otp = generateOtp();
    const otp_hash = await hashOtp(otp);

    const user = existing
      ? await prisma.user.update({
          where: { id: existing.id },
          data: { password_hash, name: name.trim(), otp_hash, otp_purpose: 'verify', otp_expires_at: otpExpiryDate() },
        })
      : await prisma.user.create({
          data: {
            email: normalizedEmail,
            password_hash,
            name: name.trim(),
            otp_hash,
            otp_purpose: 'verify',
            otp_expires_at: otpExpiryDate(),
          },
        });

    await sendOtpEmail(user.email, otp, 'verify');

    return res.status(201).json({
      success: true,
      pendingVerification: true,
      email: user.email,
      message: 'We emailed you a 6-digit code. Enter it to finish creating your account.',
    });
  } catch (err) {
    console.error('POST /api/auth/register error:', err.message);
    return res.status(500).json({ error: 'Failed to register. Please try again.' });
  }
});

// ── POST /api/auth/verify-email ── (confirms the signup OTP, then logs the user in)
app.post('/api/auth/verify-email', async (req, res) => {
  try {
    const { email, otp } = req.body;
    if (!email || !otp) {
      return res.status(400).json({ error: 'email and otp are required.' });
    }

    const user = await prisma.user.findUnique({ where: { email: email.toLowerCase().trim() } });
    if (!user || !user.otp_hash || user.otp_purpose !== 'verify') {
      return res.status(400).json({ error: 'No pending verification for this email.' });
    }
    if (new Date() > user.otp_expires_at) {
      return res.status(400).json({ error: 'Code expired. Please request a new one.' });
    }
    if (!(await compareOtp(otp, user.otp_hash))) {
      return res.status(400).json({ error: 'Incorrect code.' });
    }

    const verified = await prisma.user.update({
      where: { id: user.id },
      data: { email_verified: true, otp_hash: null, otp_purpose: null, otp_expires_at: null },
    });

    const token = signToken(verified);
    return res.json({
      success: true,
      token,
      user: { id: verified.id, email: verified.email, name: verified.name },
    });
  } catch (err) {
    console.error('POST /api/auth/verify-email error:', err.message);
    return res.status(500).json({ error: 'Failed to verify email.' });
  }
});

// ── POST /api/auth/resend-otp ── (re-sends the signup verification code)
app.post('/api/auth/resend-otp', async (req, res) => {
  try {
    const { email } = req.body;
    if (!email) return res.status(400).json({ error: 'email is required.' });

    const user = await prisma.user.findUnique({ where: { email: email.toLowerCase().trim() } });
    if (!user || user.email_verified) {
      return res.status(400).json({ error: 'No pending verification for this email.' });
    }

    const otp = generateOtp();
    const otp_hash = await hashOtp(otp);
    await prisma.user.update({
      where: { id: user.id },
      data: { otp_hash, otp_purpose: 'verify', otp_expires_at: otpExpiryDate() },
    });
    await sendOtpEmail(user.email, otp, 'verify');

    return res.json({ success: true, message: 'A new code has been sent.' });
  } catch (err) {
    console.error('POST /api/auth/resend-otp error:', err.message);
    return res.status(500).json({ error: 'Failed to resend code.' });
  }
});

// ── POST /api/auth/login ──
app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'email and password are required.' });
    }

    const user = await prisma.user.findUnique({ where: { email: email.toLowerCase().trim() } });
    if (!user || !(await comparePassword(password, user.password_hash))) {
      return res.status(401).json({ error: 'Invalid email or password.' });
    }
    if (!user.email_verified) {
      return res.status(403).json({ error: 'Please verify your email first.', pendingVerification: true, email: user.email });
    }

    const token = signToken(user);
    return res.json({
      success: true,
      token,
      user: { id: user.id, email: user.email, name: user.name },
    });
  } catch (err) {
    console.error('POST /api/auth/login error:', err.message);
    return res.status(500).json({ error: 'Failed to log in.' });
  }
});

// ── POST /api/auth/forgot-password ── (emails a reset OTP)
app.post('/api/auth/forgot-password', async (req, res) => {
  try {
    const { email } = req.body;
    if (!email) return res.status(400).json({ error: 'email is required.' });

    const user = await prisma.user.findUnique({ where: { email: email.toLowerCase().trim() } });
    // Always respond success (don't leak whether an email is registered)
    if (user && user.email_verified) {
      const otp = generateOtp();
      const otp_hash = await hashOtp(otp);
      await prisma.user.update({
        where: { id: user.id },
        data: { otp_hash, otp_purpose: 'reset', otp_expires_at: otpExpiryDate() },
      });
      await sendOtpEmail(user.email, otp, 'reset');
    }

    return res.json({ success: true, message: 'If that email is registered, a reset code has been sent.' });
  } catch (err) {
    console.error('POST /api/auth/forgot-password error:', err.message);
    return res.status(500).json({ error: 'Failed to send reset code.' });
  }
});

// ── POST /api/auth/reset-password ── (verifies the reset OTP and sets a new password)
app.post('/api/auth/reset-password', async (req, res) => {
  try {
    const { email, otp, new_password } = req.body;
    if (!email || !otp || !new_password) {
      return res.status(400).json({ error: 'email, otp, and new_password are required.' });
    }
    if (new_password.length < 6) {
      return res.status(422).json({ error: 'Password must be at least 6 characters.' });
    }

    const user = await prisma.user.findUnique({ where: { email: email.toLowerCase().trim() } });
    if (!user || !user.otp_hash || user.otp_purpose !== 'reset') {
      return res.status(400).json({ error: 'No pending password reset for this email.' });
    }
    if (new Date() > user.otp_expires_at) {
      return res.status(400).json({ error: 'Code expired. Please request a new one.' });
    }
    if (!(await compareOtp(otp, user.otp_hash))) {
      return res.status(400).json({ error: 'Incorrect code.' });
    }

    const password_hash = await hashPassword(new_password);
    const updated = await prisma.user.update({
      where: { id: user.id },
      data: { password_hash, otp_hash: null, otp_purpose: null, otp_expires_at: null },
    });

    const token = signToken(updated);
    return res.json({
      success: true,
      token,
      user: { id: updated.id, email: updated.email, name: updated.name },
    });
  } catch (err) {
    console.error('POST /api/auth/reset-password error:', err.message);
    return res.status(500).json({ error: 'Failed to reset password.' });
  }
});

// ── GET /api/auth/me ── (validate an existing token on app load)
app.get('/api/auth/me', requireAuth, (req, res) => {
  res.json({ success: true, user: { id: req.user.id, email: req.user.email, name: req.user.name } });
});

// ── POST /api/recommendations ──
app.post('/api/recommendations', async (req, res) => {
  try {
    const userPreferences = req.body;

    // Fetch db_stats from Prisma
    const dbStats = await getDbStats();

    // Call ML service
    const mlResponse = await axios.post(`${ML_URL}/recommend`, {
      user_preferences: userPreferences,
      db_stats: dbStats,
    });

    return res.json(mlResponse.data);
  } catch (err) {
    console.error('POST /api/recommendations error:', err.message);
    if (err.code === 'ECONNREFUSED') {
      return res.status(503).json({
        error: 'ML service is not available. Please ensure the recommendation engine is running.',
        results: [],
      });
    }
    return res.status(500).json({
      error: 'Something went wrong while fetching recommendations.',
      results: [],
    });
  }
});

// ── POST /api/rate-pg ──
app.post('/api/rate-pg', requireAuth, async (req, res) => {
  try {
    const { pg_id, rating } = req.body;

    if (pg_id == null || rating == null) {
      return res.status(400).json({ error: 'pg_id and rating are required' });
    }
    if (rating < 1 || rating > 5) {
      return res.status(422).json({ error: 'Rating must be between 1 and 5' });
    }

    // One rating per user per PG — resubmitting updates their existing rating
    await prisma.rating.upsert({
      where: { pg_id_user_id: { pg_id: Number(pg_id), user_id: req.user.id } },
      update: { rating: Number(rating) },
      create: { pg_id: Number(pg_id), rating: Number(rating), user_id: req.user.id },
    });

    // Fetch updated stats
    const agg = await prisma.rating.aggregate({
      where: { pg_id: Number(pg_id) },
      _avg: { rating: true },
      _count: { rating: true },
    });

    return res.json({
      success: true,
      pg_id: Number(pg_id),
      average_rating: agg._avg.rating !== null ? parseFloat(agg._avg.rating.toFixed(2)) : 3.5,
      rating_count: agg._count.rating,
    });
  } catch (err) {
    console.error('POST /api/rate-pg error:', err.message);
    return res.status(500).json({ error: 'Failed to save rating.' });
  }
});

// ── POST /api/submit-review ──
app.post('/api/submit-review', requireAuth, async (req, res) => {
  try {
    const { pg_id, review_text } = req.body;

    if (pg_id == null || !review_text || !review_text.trim()) {
      return res.status(400).json({ error: 'pg_id and review_text are required' });
    }

    // Call ML service for sentiment analysis
    const mlResponse = await axios.post(`${ML_URL}/analyze-sentiment`, {
      review_text: review_text.trim(),
    });
    const { sentiment_score } = mlResponse.data;

    // One review per user per PG — resubmitting updates their existing review
    await prisma.review.upsert({
      where: { pg_id_user_id: { pg_id: Number(pg_id), user_id: req.user.id } },
      update: { review_text: review_text.trim(), sentiment_score },
      create: {
        pg_id: Number(pg_id),
        review_text: review_text.trim(),
        sentiment_score,
        user_id: req.user.id,
      },
    });

    // Fetch updated stats
    const pgId = Number(pg_id);
    const allReviews = await prisma.review.findMany({
      where: { pg_id: pgId },
      orderBy: { id: 'asc' },
    });

    const reviewCount = allReviews.length;
    const avgSentiment =
      reviewCount > 0
        ? parseFloat(
            (allReviews.reduce((sum, r) => sum + r.sentiment_score, 0) / reviewCount).toFixed(4)
          )
        : 0.5;

    function getLabel(score) {
      if (score >= 0.9) return 'Excellent';
      if (score >= 0.6) return 'Good';
      if (score >= 0.4) return 'Average';
      return 'Poor';
    }

    function starEquivalent(score) {
      return parseFloat((1.0 + score * 4.0).toFixed(2));
    }

    const reviews = allReviews.map((r) => ({
      text: r.review_text,
      sentiment_score: r.sentiment_score,
      sentiment_label: getLabel(r.sentiment_score),
    }));

    return res.json({
      success: true,
      pg_id: pgId,
      sentiment_score,
      sentiment_label: getLabel(sentiment_score),
      star_equivalent: starEquivalent(sentiment_score),
      avg_sentiment: avgSentiment,
      review_count: reviewCount,
      reviews: reviews.slice(-5),
    });
  } catch (err) {
    console.error('POST /api/submit-review error:', err.message);
    if (err.code === 'ECONNREFUSED') {
      return res.status(503).json({ error: 'ML service is not available for sentiment analysis.' });
    }
    return res.status(500).json({ error: 'Failed to submit review.' });
  }
});

// ── GET /api/reviews/:pgId ──
app.get('/api/reviews/:pgId', async (req, res) => {
  try {
    const pgId = Number(req.params.pgId);

    const allReviews = await prisma.review.findMany({
      where: { pg_id: pgId },
      orderBy: { id: 'asc' },
    });

    const reviewCount = allReviews.length;
    const avgSentiment =
      reviewCount > 0
        ? parseFloat(
            (allReviews.reduce((sum, r) => sum + r.sentiment_score, 0) / reviewCount).toFixed(4)
          )
        : 0.5;

    function getLabel(score) {
      if (score >= 0.9) return 'Excellent';
      if (score >= 0.6) return 'Good';
      if (score >= 0.4) return 'Average';
      return 'Poor';
    }

    const reviews = allReviews.map((r) => ({
      id: r.id,
      text: r.review_text,
      sentiment_score: r.sentiment_score,
      sentiment_label: getLabel(r.sentiment_score),
    }));

    return res.json({
      success: true,
      pg_id: pgId,
      reviews: reviews.slice(-20),
      avg_sentiment: avgSentiment,
      review_count: reviewCount,
    });
  } catch (err) {
    console.error('GET /api/reviews/:pgId error:', err.message);
    return res.status(500).json({ error: 'Failed to fetch reviews.' });
  }
});

// ── Health check ──
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', service: 'express-gateway' });
});

app.listen(PORT, () => {
  console.log(`🚀 Express Gateway running on http://localhost:${PORT}`);
});
