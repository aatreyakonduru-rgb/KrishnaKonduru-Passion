# Data Access Rules for Acme Claims

## Row-Level Security (RLS) Policy

### Policy Name
`DEV01_IAM.IAM_RSTRCTD_POLICY.RP_TNNT_ACCESS`

### Enforcement Columns
- `RAW_TNNT_ID` (Tenant ID) — NUMBER(38,0), NOT NULL
- `RAW_OFSHR_ACSBL_IND` (Offshore Accessibility Indicator) — VARCHAR(1), NOT NULL, default `N`

### Rule
All queries against CLAIMS_UI_DATA tables MUST filter by:
1. User's assigned tenant ID(s)
2. Offshore accessibility flag (if user is offshore, only rows with `RAW_OFSHR_ACSBL_IND = 'Y'` are visible)

### Enforcement
- Snowflake RLS policy applied at table level
- Application-level check in Django ORM (filter by `request.user.tenant_id`)

## Shared Columns (All Tables)
Every table in `CLAIMS_UI_DATA` includes these audit/security columns:
- `RAW_LOAD_DTM` — TIMESTAMP_NTZ(9), NOT NULL
- `RAW_RUN_ID` — VARCHAR(255), NOT NULL, default `NA`
- `RAW_SOR_CD` — VARCHAR(10), NOT NULL, default `NA`
- `KF_TMS` — TIMESTAMP_NTZ(9), nullable
- `RAW_SCRTY_LVL_CD` — VARCHAR(10), NOT NULL, default `UNK`
- `RAW_OFSHR_ACSBL_IND` — VARCHAR(1), NOT NULL, default `N`
- `RAW_CLNT_ID` — NUMBER(38,0), NOT NULL
- `RAW_TNNT_ID` — NUMBER(38,0), NOT NULL
- `RAW_CREAT_DTM` — TIMESTAMP_NTZ(9), NOT NULL, default CURRENT_TIMESTAMP()
- `RAW_INCRMNTL_LOAD_DTM` — TIMESTAMP_NTZ(9), NOT NULL

## Versioning Defaults
- `VRSN_OPEN_DTM` — TIMESTAMP_NTZ(9), default CURRENT_TIMESTAMP()
- `VALID_TO_DTM` — TIMESTAMP_NTZ(9), default `9999-12-31 00:00:00`

## Role-Based Access Control (RBAC)

### Application Roles
- `ACME-FINANCE-*` — Finance users (PMC, PCMH screens)
- `ACME-PROVIDER-CONTRACT-*` — Provider users (Provider Grouping, Contract screens)
- `ACME-PROVIDER-CONTRACT-APPROVER` — Can review and approve Provider Group configurations
- `ACME-PROVIDER-CONTRACT-ADMIN` — Can manage the approver list + APPROVER capabilities

### Snowflake Roles
- `SDLC_UI_READ` — Read-only access to CLAIMS_UI_DATA schema
- `SDLC_UI_WRITE` — Write access (ETL jobs only)
- `SDLC_UI_ADMIN` — Full admin (DDL, grants)

## Data Access Patterns

### Good: Tenant-Filtered Query
```sql
SELECT * FROM VBC_UI_CNTRCT_PARM
WHERE RAW_TNNT_ID = :tenant_id
  AND VALID_TO_DTM = '9999-12-31 00:00:00'
```

### Bad: Unfiltered Query (RLS will enforce, but inefficient)
```sql
SELECT * FROM VBC_UI_CNTRCT_PARM
```

### Good: Django ORM with Tenant Filter
```python
from apps.contracts.models import Contract

contracts = Contract.objects.filter(
    raw_tnnt_id=request.user.tenant_id,
    valid_to_dtm='9999-12-31 00:00:00'
)
```

### Bad: Raw SQL without Tenant Filter
```python
cursor.execute("SELECT * FROM VBC_UI_CNTRCT_PARM")
```

## Snowflake Connection Identity

Which Snowflake login the app uses depends on where it runs:

| Where the app runs | Snowflake login |
|---|---|
| Devin Cloud VM (`/devin-window`, `/argus` inside a session, `/build-check`, the testing agent, any app Devin starts) | The nonprod Snowflake **service account**, signed in without a browser (key pair or programmatic access token) from a Devin org secret |
| A developer's or tester's PC, Devin Desktop or Devin Local (`/test-on-pc`) | Unchanged: the person's own ID through Okta |
| Deployed SIT, UAT and prod | Unchanged: the application account from AWS Secrets Manager (`ReduceReuseRecycle.snowflake_conn`, `web-admin/lib/snowflake/rrr-connector.ts`) |

On the Devin Cloud VM:
- Never connect as a personal ID. Personal IDs sign in through Okta in an external browser, and the VM's browser cannot reach SSO.
- Never set `authenticator=externalbrowser`, or a personal user name or password.
- The Snowflake nonprod MCP (`sql_exec_tool`) is for Devin's own queries. It signs in with OAuth as the requester, in their browser. The app cannot connect through it.
- If the service-account secret is not provisioned, print `SKIP: snowflake — service account not yet provisioned` and report anything that needs Snowflake as "not run", never "passed". Don't ask the user for their own login and don't wait for one.
- Never print, log or commit the key or token.

Don't know yet: the service account's name, its secret name, and how the Python APIs will read it (today they only read AWS Secrets Manager). Add them here once provisioned; don't guess.

## Offshore Access Rules
- If user is offshore (`user.is_offshore == True`):
  - Only rows with `RAW_OFSHR_ACSBL_IND = 'Y'` are accessible
  - PII/PHI columns are masked or denied
- If user is onshore:
  - All rows for assigned tenant(s) are accessible

## Audit Requirements
- All data access MUST be logged with:
  - User ID
  - Tenant ID
  - Timestamp
  - Query executed
  - Rows returned
- Use Snowflake `QUERY_HISTORY` view for compliance audits

## References
- Snowflake RLS: https://docs.snowflake.com/en/user-guide/security-row
- Django Tenant Filtering: [Internal wiki]
- Acme Data Access Policy: [Internal link]
