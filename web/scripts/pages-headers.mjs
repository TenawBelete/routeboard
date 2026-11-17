// Writes dist/_headers for Cloudflare Pages: the same security headers Caddy sends locally, with the
// API and offline-copy addresses added to the content security policy. Run after `vite build`.
import { writeFileSync } from "node:fs";

const origin = (u) => { try { return u ? new URL(u).origin : ""; } catch { return ""; } };
const connect = ["'self'", origin(process.env.VITE_API_BASE), origin(process.env.VITE_OFFLINE_URL)].filter(Boolean).join(" ");
const csp = `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src ${connect}; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`;

const headers = `/*
  Content-Security-Policy: ${csp}
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: DENY
  Permissions-Policy: geolocation=(), camera=(), microphone=()
  Strict-Transport-Security: max-age=31536000; includeSubDomains

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/world.json
  Cache-Control: public, max-age=604800
`;
writeFileSync(new URL("../dist/_headers", import.meta.url), headers);
console.log(`_headers written (connect-src ${connect})`);
