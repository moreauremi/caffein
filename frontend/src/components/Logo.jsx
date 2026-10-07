// SPDX-License-Identifier: AGPL-3.0-or-later
// Logo adaptatif : le pictogramme reste orange, le mot-symbole suit la couleur du texte
// (remplace logo_transparent.png / logo_transparent_white.png de la doc).
export default function Logo({ size = 28, wordmark = true, className = '' }) {
  return (
    <span className={`row ${className}`} style={{ gap: 9 }}>
      <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
        <rect width="64" height="64" rx="17" fill="#E8510E" />
        <path d="M32 13c-9.5 0-16 8.6-16 19s6.5 19 16 19 16-8.6 16-19-6.5-19-16-19Z" fill="#fff" />
        <path d="M33.5 15.5c-5 5-5 11.5-1.5 16.5s3.5 11.5-1.5 16.5" fill="none" stroke="#E8510E" strokeWidth="4" strokeLinecap="round" />
      </svg>
      {wordmark && (
        <span style={{ fontWeight: 700, fontSize: size * 0.68, letterSpacing: '-0.035em', lineHeight: 1 }}>caffein</span>
      )}
    </span>
  )
}
