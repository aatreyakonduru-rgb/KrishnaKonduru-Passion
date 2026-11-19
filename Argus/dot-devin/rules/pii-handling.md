# PII/PHI Handling Rules for Acme Claims

## Definitions
- **PII** (Personally Identifiable Information): SSN, DOB, full name, address, phone, email
- **PHI** (Protected Health Information): Medical records, diagnoses, treatment, claims, member IDs

## Mandatory Rules

### 1. No PII/PHI in Logs
- **Rule**: Never log PII/PHI in application logs, error messages, or debug output
- **Enforcement**: Pre-commit regex scan + runtime log sanitization
- **Alternative**: Log sanitized IDs (e.g., `member_id_hash`) or use `[REDACTED]`
- **Violation Severity**: CRITICAL

### 2. No PII/PHI in Client-Side Code
- **Rule**: Never include PII/PHI in JavaScript, HTML, or browser storage
- **Enforcement**: Code review + automated scan
- **Alternative**: Fetch on-demand from API; never cache in localStorage
- **Violation Severity**: CRITICAL

### 3. Database Column Encryption
- **Rule**: PII/PHI columns MUST be encrypted at rest
- **Enforcement**: Snowflake encryption enabled (default); verify column-level encryption for sensitive fields
- **Alternative**: Use Snowflake Dynamic Data Masking for non-privileged users
- **Violation Severity**: HIGH

### 4. Row-Level Security (RLS)
- **Rule**: All tables with PII/PHI MUST enforce row-level security by tenant
- **Enforcement**: `DEV01_IAM.IAM_RSTRCTD_POLICY.RP_TNNT_ACCESS` applied to all CLAIMS_UI_DATA tables
- **Columns**: `RAW_TNNT_ID`, `RAW_OFSHR_ACSBL_IND`
- **Violation Severity**: CRITICAL

### 5. Offshore Accessibility Flag
- **Rule**: PII/PHI MUST respect `RAW_OFSHR_ACSBL_IND` flag (default: `N`)
- **Enforcement**: RLS policy + application-level check
- **Alternative**: Deny access if flag is `N` and user is offshore
- **Violation Severity**: HIGH

### 6. Audit Logging
- **Rule**: All PII/PHI access MUST be logged with user, timestamp, and purpose
- **Enforcement**: Snowflake query history + application audit trail
- **Alternative**: Use Snowflake `QUERY_HISTORY` view for compliance audits
- **Violation Severity**: MEDIUM

### 7. Data Minimization
- **Rule**: Only fetch PII/PHI fields required for the specific use case
- **Enforcement**: Code review + SQL query analysis
- **Alternative**: Use `SELECT column1, column2` instead of `SELECT *`
- **Violation Severity**: MEDIUM

### 8. Secure Transmission
- **Rule**: PII/PHI MUST be transmitted over HTTPS/TLS only
- **Enforcement**: API Gateway + Django HTTPS enforcement
- **Alternative**: Reject HTTP requests
- **Violation Severity**: CRITICAL

### 9. Data Retention
- **Rule**: PII/PHI MUST be purged per retention policy (7 years for claims data)
- **Enforcement**: Scheduled ETL job + manual audit
- **Alternative**: Archive to secure cold storage; delete from active tables
- **Violation Severity**: MEDIUM

### 10. Third-Party Sharing
- **Rule**: PII/PHI MUST NOT be shared with third parties without BAA (Business Associate Agreement)
- **Enforcement**: Legal review + data flow diagram
- **Alternative**: Anonymize/de-identify before sharing
- **Violation Severity**: CRITICAL

## PII/PHI Columns in CLAIMS_UI_DATA
(Partial list; see `DB_TABLE_REGISTRY.yaml` for full inventory)
- `VBC_UI_CNTRCT_PARM`: Contract parameters (may contain member counts, not direct PII)
- `VBC_UI_MBR_ATRBN`: Member attribution (member IDs, DOB, SSN if present)
- `VBC_UI_PRVDR_GRP`: Provider groups (TIN, NPI — considered PII)
- `VBC_UI_CLMS`: Claims data (member ID, diagnosis codes — PHI)

## Sanitization Patterns
```python
# Good: Sanitized logging
logger.info(f"Processing member {hash_member_id(member_id)}")

# Bad: PII in logs
logger.info(f"Processing member {member_id} with SSN {ssn}")
```

```sql
-- Good: Parameterized query
SELECT * FROM VBC_UI_MBR_ATRBN WHERE MBR_ID = %s

-- Bad: String concatenation (SQL injection + PII exposure)
SELECT * FROM VBC_UI_MBR_ATRBN WHERE MBR_ID = '{member_id}'
```

## References
- HIPAA Security Rule: https://www.hhs.gov/hipaa/for-professionals/security/
- Snowflake Data Masking: https://docs.snowflake.com/en/user-guide/security-column-ddm
- Acme PII/PHI Policy: [Internal link]
