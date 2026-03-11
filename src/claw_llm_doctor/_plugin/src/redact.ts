const SECRET_PATTERNS: RegExp[] = [
  // API keys & tokens (common prefixes)
  /\b(sk-[a-zA-Z0-9_-]{20,})\b/g,
  /\b(api[_-]?key\s*[:=]\s*["']?)([a-zA-Z0-9_-]{16,})/gi,
  /\b(bearer\s+)([a-zA-Z0-9_.\-/+=]{20,})/gi,
  /\b(token\s*[:=]\s*["']?)([a-zA-Z0-9_.\-/+=]{16,})/gi,
  // AWS style
  /\b(AKIA[0-9A-Z]{16})\b/g,
  // Generic long hex/base64 secrets
  /\b(secret\s*[:=]\s*["']?)([a-zA-Z0-9_.\-/+=]{20,})/gi,
  // Password fields
  /\b(password\s*[:=]\s*["']?)([^\s"']{8,})/gi,
];

const REDACTED = "[REDACTED]";

/**
 * Recursively walk a value and redact strings that look like secrets.
 * Returns a deep-cloned copy — the original is never mutated.
 */
export function redact(value: unknown): unknown {
  if (value === null || value === undefined) return value;

  if (typeof value === "string") {
    return redactString(value);
  }

  if (Array.isArray(value)) {
    return value.map(redact);
  }

  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      // Redact values whose key name suggests a secret
      if (isSecretKey(k) && typeof v === "string") {
        out[k] = REDACTED;
      } else {
        out[k] = redact(v);
      }
    }
    return out;
  }

  return value;
}

function redactString(s: string): string {
  let result = s;
  for (const pattern of SECRET_PATTERNS) {
    // Reset lastIndex for global patterns
    pattern.lastIndex = 0;
    result = result.replace(pattern, (match, ...groups) => {
      // Keep the label/prefix, redact the secret part
      if (groups.length >= 2 && typeof groups[1] === "string") {
        return (groups[0] as string) + REDACTED;
      }
      return REDACTED;
    });
  }
  return result;
}

const SECRET_KEY_RE =
  /^(api[_-]?key|secret|token|password|credential|auth|bearer|access[_-]?key|private[_-]?key)$/i;

function isSecretKey(key: string): boolean {
  return SECRET_KEY_RE.test(key);
}
