# Secure Coding Rules for Acme Claims Agentic SDLC

## Mandatory Rules (Enforced by AI Guardrails)

### 1. No Hardcoded Secrets
- **Rule**: Never hardcode API keys, passwords, tokens, or connection strings in source code
- **Enforcement**: Pre-commit hook scans for patterns like `password=`, `api_key=`, AWS keys
- **Alternative**: Use environment variables, AWS Secrets Manager, or Kubernetes secrets
- **Violation Severity**: CRITICAL — blocks PR approval

### 2. PII/PHI Handling
- **Rule**: No PII/PHI in logs, error messages, or client-side code
- **Enforcement**: Regex scan for SSN, DOB, member IDs in logs/exceptions
- **Alternative**: Log sanitized IDs only; use `[REDACTED]` placeholders
- **Violation Severity**: HIGH — requires immediate remediation

### 3. SQL Injection Prevention
- **Rule**: All SQL queries MUST use parameterized statements or ORM
- **Enforcement**: DB_PROMPT_12 AI Guardrails check for string concatenation in SQL
- **Alternative**: Use Django ORM `.filter()` or `snowflake.connector` bind variables
- **Violation Severity**: CRITICAL — blocks deployment

### 4. JWT Verification
- **Rule**: All JWT tokens MUST verify signature, issuer, audience, and expiration
- **Enforcement**: Code review checklist + unit test requirement
- **Current Issue**: `verify_aud: False` in `libs/auth.py:84` (see SEC-TOKEN-001)
- **Violation Severity**: HIGH

### 5. HTTPS Only
- **Rule**: All external API calls MUST use HTTPS
- **Enforcement**: Linter rule + runtime check
- **Alternative**: No HTTP fallback allowed
- **Violation Severity**: MEDIUM

### 6. Input Validation
- **Rule**: Validate all user inputs (type, length, format, range)
- **Enforcement**: Django form validation + Pydantic schemas
- **Alternative**: Reject invalid input with 400 Bad Request
- **Violation Severity**: MEDIUM

### 7. Error Message Sanitization
- **Rule**: Never expose stack traces, DB schema, or internal paths to end users
- **Enforcement**: Custom exception handler in Django + Next.js error boundaries
- **Alternative**: Log full error server-side; return generic message to client
- **Violation Severity**: MEDIUM

### 8. Rate Limiting
- **Rule**: All public endpoints MUST have rate limiting
- **Enforcement**: Django middleware or API Gateway throttling
- **Alternative**: 429 Too Many Requests after threshold
- **Violation Severity**: MEDIUM

### 9. CORS Configuration
- **Rule**: CORS allowed origins MUST be explicitly whitelisted (no `*`)
- **Enforcement**: Django CORS settings review
- **Alternative**: Environment-specific origin lists
- **Violation Severity**: MEDIUM

### 10. Dependency Scanning
- **Rule**: All dependencies MUST be scanned for known vulnerabilities
- **Enforcement**: `pip-audit` or Snyk in CI/CD
- **Alternative**: Pin versions; update regularly
- **Violation Severity**: MEDIUM

## Code Review Checklist
- [ ] No hardcoded secrets
- [ ] PII/PHI sanitized in logs
- [ ] SQL queries parameterized
- [ ] JWT verification complete
- [ ] HTTPS enforced
- [ ] Input validation present
- [ ] Error messages sanitized
- [ ] Rate limiting configured
- [ ] CORS whitelist verified
- [ ] Dependencies scanned

## Known Issues to Remediate
- **SEC-TOKEN-001**: JWT audience verification disabled (`verify_aud: False`)
- **SEC-CRED-002**: SIT OIDC URL hardcoded as Python default
- **FE-SEC-001**: Axios Authorization header commented out (API calls unauthenticated)
- **FE-SEC-002**: Hardcoded AWS API Gateway URLs in client-side source

## References
- OWASP Top 10: https://owasp.org/www-project-top-ten/
- Django Security: https://docs.djangoproject.com/en/5.1/topics/security/
- Snowflake Security: https://docs.snowflake.com/en/user-guide/security
