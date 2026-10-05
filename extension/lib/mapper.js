// Pure logic: map a form-field label to a value from the user's profile. No DOM, fully unit-tested.
(function (g) {
  'use strict';
  const JP = (g.JP = g.JP || {});

  // Questions we never auto-answer from a profile guess: the backend only answers them from a bank YOU filled in.
  const SENSITIVE = /gender|race|ethnic|veteran|disabilit|sexual|pronoun|criminal|convict|felony|salary|compensation|pay expect|date of birth|\bssn\b|social security|citizenship|visa|religio|hispanic|lgbt/i;

  function normalize(s) {
    return String(s || '').toLowerCase().replace(/\(?\brequired\b\)?|\*/g, ' ').replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function splitName(full) {
    const parts = String(full || '').trim().split(/\s+/).filter(Boolean);
    return [parts[0] || '', parts.slice(1).join(' ')];
  }

  const isSensitive = (label) => SENSITIVE.test(label || '');

  // [pattern, extractor]. First match wins. Order matters (specific before generic).
  const RULES = [
    [/\b(company|employer|school|university|reference|manager|supervisor)\b.*\bname\b|\bname\b.*\b(company|employer|school)\b/, () => null],
    [/country code|phone type|extension/, () => null],
    [/first\s*name|given name|forename/, (p) => p.first_name || splitName(p.full_name)[0]],
    [/last\s*name|family name|surname/, (p) => p.last_name || splitName(p.full_name)[1]],
    [/^(your |legal |full |preferred )?name$|^full legal name$/, (p) => p.full_name || [p.first_name, p.last_name].filter(Boolean).join(' ')],
    [/e ?mail/, (p) => p.email],
    [/phone|mobile|telephone|cell/, (p) => p.phone],
    [/linkedin/, (p) => p.linkedin],
    [/github/, (p) => p.github],
    [/portfolio|personal (web)?site|website|^url$|blog/, (p) => p.website || p.github || p.linkedin],
    [/\bzip\b|postal/, (p) => p.zip],
    [/\bcity\b/, (p) => p.city || String(p.location || '').split(',')[0].trim()],
    [/\bstate\b|province|region/, (p) => p.state || String(p.location || '').split(',')[1]?.trim()],
    [/\bcountry\b/, (p) => p.country],
    [/^(current )?(location|address)|where are you (located|based)/, (p) => p.location || [p.city, p.state].filter(Boolean).join(', ')],
    [/current (company|employer)|most recent (company|employer)/, (p) => p.current_company],
    [/current (job )?title|current position|most recent (job )?title/, (p) => p.current_title],
    [/notice period|available to start|when can you start|earliest start|start date/, (p) => p.notice_period],
  ];

  function mapField(label, profile) {
    const l = normalize(label);
    if (!l || isSensitive(label)) return null;
    // "Years of experience" only when generic; "...with Python" goes to the resume-aware backend instead.
    if (/years/.test(l) && /experience/.test(l)) {
      if (/experience\s+(with|in|using|working|managing|building|developing|as|on)\b/.test(l) || /\b(with|using)\b/.test(l)) return null;
      return profile.years_experience != null ? String(Math.round(Number(profile.years_experience))) : null;
    }
    for (const [re, get] of RULES) {
      if (re.test(l)) {
        const v = get(profile || {});
        return v ? String(v) : null;
      }
    }
    return null;
  }

  // Choose the best option for an answer: exact, then prefix, then containment (so "Yes" matches "Yes, I am authorized").
  function pickOption(answer, options) {
    const a = normalize(answer);
    if (!a) return null;
    const opts = options.map((o) => [o, normalize(typeof o === 'string' ? o : o.text)]);
    for (const [o, n] of opts) if (n === a) return o;
    for (const [o, n] of opts) if (n && (n.startsWith(a) || a.startsWith(n))) return o;
    for (const [o, n] of opts) if (n && (n.includes(a) || a.includes(n))) return o;
    return null;
  }

  // Consent boxes we are willing to tick; anything legal-ish beyond this is left for a human.
  const CONSENT_OK = /privacy|data (processing|protection)|terms|certify|acknowledge|accurate|true and complete|consent to (the )?(processing|storage)|read and (agree|understand)/i;
  const CONSENT_NO = /arbitration|non-?compete|background check|drug|waive|release|text message|sms|marketing|newsletter|subscribe/i;
  const isAcceptableConsent = (label) => CONSENT_OK.test(label || '') && !CONSENT_NO.test(label || '');

  const api = { normalize, splitName, isSensitive, mapField, pickOption, isAcceptableConsent };
  JP.mapper = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : window);
