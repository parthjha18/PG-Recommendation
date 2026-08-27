// backend/mailer.js — sends OTP emails via Gmail SMTP (Nodemailer)
import nodemailer from 'nodemailer';

const transporter = nodemailer.createTransport({
  service: 'gmail',
  auth: {
    user: process.env.GMAIL_USER,
    pass: process.env.GMAIL_APP_PASSWORD,
  },
  connectionTimeout: 8000,
  greetingTimeout: 8000,
  socketTimeout: 8000,
});

export async function sendOtpEmail(to, otp, purpose) {
  const subject =
    purpose === 'reset' ? 'PG Finder — Reset your password' : 'PG Finder — Verify your email';
  const heading = purpose === 'reset' ? 'Reset your password' : 'Verify your email';
  const body =
    purpose === 'reset'
      ? 'Use this code to reset your password. It expires in 10 minutes.'
      : 'Use this code to verify your email and finish creating your account. It expires in 10 minutes.';

  try {
    await transporter.sendMail({
      from: `"PG Finder" <${process.env.GMAIL_USER}>`,
      to,
      subject,
      text: `${heading}\n\nYour code: ${otp}\n\n${body}\n\nIf you didn't request this, you can ignore this email.`,
      html: `
        <div style="font-family: sans-serif; max-width: 420px; margin: auto;">
          <h2 style="color:#ff6b35;">${heading}</h2>
          <p style="color:#444;">${body}</p>
          <div style="font-size: 32px; font-weight: 700; letter-spacing: 6px; background: #f4f4f4; padding: 16px 24px; border-radius: 10px; text-align: center; margin: 20px 0;">
            ${otp}
          </div>
          <p style="color:#888; font-size: 13px;">If you didn't request this, you can safely ignore this email.</p>
        </div>
      `,
    });
  } catch (err) {
    // Dev fallback: some networks (corporate wifi) block outbound SMTP entirely.
    // Don't fail the request over it — print the code so local testing still works.
    console.warn(`⚠️  Could not send OTP email (${err.code || err.message}). Falling back to console.`);
    console.log(`\n📧  OTP for ${to} [${purpose}]: ${otp}\n`);
  }
}
