// Contact links for the site's author. Plain icons are used on purpose (a speech bubble, an envelope,
// a profile card) rather than the companies' own logos; the label next to each says which service it is.
const WHATSAPP = "https://wa.me/34653650787";
const EMAIL = "mailto:tenaw.belete@student.ie.edu";
const LINKEDIN = "https://www.linkedin.com/in/tenaw-belete";

const Icon = ({ kind }: { kind: "chat" | "mail" | "profile" }) => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === "chat" && <><path d="M21 11.5a8.5 8.5 0 0 1-12.6 7.4L3 20.5l1.7-5.2A8.5 8.5 0 1 1 21 11.5z" /><path d="M9 9.5c0 3 2.5 5.5 5.5 5.5" /></>}
    {kind === "mail" && <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M3.5 6.5l8.5 6.5 8.5-6.5" /></>}
    {kind === "profile" && <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="10" r="2.2" /><path d="M5.5 17c.6-2 2-3 3.5-3s2.9 1 3.5 3" /><path d="M15 9h3.5M15 12.5h3.5" /></>}
  </svg>
);

const LINKS = [
  { kind: "chat" as const, href: WHATSAPP, label: "WhatsApp", detail: "+34 653 650 787" },
  { kind: "mail" as const, href: EMAIL, label: "Email", detail: "tenaw.belete@student.ie.edu" },
  { kind: "profile" as const, href: LINKEDIN, label: "LinkedIn", detail: "linkedin.com/in/tenaw-belete" },
];

/** `compact`: icon and service name only, for the footer. Otherwise full rows with the address shown. */
export function Contact({ compact = false }: { compact?: boolean }) {
  if (compact)
    return (
      <span className="contact-inline">
        {LINKS.map((l) => <a key={l.label} href={l.href} target="_blank" rel="noreferrer noopener" aria-label={`${l.label}: ${l.detail}`}><Icon kind={l.kind} />{l.label}</a>)}
      </span>
    );
  return (
    <ul className="contact">
      {LINKS.map((l) => (
        <li key={l.label}>
          <a href={l.href} target="_blank" rel="noreferrer noopener"><Icon kind={l.kind} /><span><b>{l.label}</b><span>{l.detail}</span></span></a>
        </li>
      ))}
    </ul>
  );
}
