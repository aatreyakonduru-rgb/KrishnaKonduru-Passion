# Pull Request: {STORY-ID} - {Story Title}

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

## Requirement
**REQ-{id}**: {Requirement title}

## Story
**STORY-{n}**: {Story title}

## Description
{Brief description of changes}

## Changes Made
### Database Layer
- {Change 1}
- {Change 2}

### API Layer
- {Change 1}
- {Change 2}

### UI Layer
- {Change 1}
- {Change 2}

### Other
- {Change 1}

## Files Changed
| File | Lines Changed | Change Type |
|------|---------------|-------------|
| {file_path} | +{added}/-{deleted} | {add/modify/delete} |
| {file_path} | +{added}/-{deleted} | {add/modify/delete} |

## Acceptance Criteria Validated
- [ ] {Acceptance criterion 1}
- [ ] {Acceptance criterion 2}
- [ ] {Acceptance criterion 3}

## Tests Included
- [ ] Unit tests
- [ ] Integration tests
- [ ] Acceptance tests

**Test Files**:
- {test_file_1}
- {test_file_2}

## AI Verification Report
**Status**: ✅ Passed / ❌ Failed

**Report**: See `{REQ-id}-STORY-{n}-AI-VERIFICATION.md`

### Security Checks
- [ ] No hardcoded secrets
- [ ] No PII in logs
- [ ] SQL parameterized (no string concatenation)
- [ ] No security violations

## KB Artifacts Updated
- [ ] DB_TABLE_REGISTRY.yaml
- [ ] DB_SCHEMA_SUMMARY.md
- [ ] API_ENDPOINT_REGISTRY.yaml
- [ ] FE_COMPONENT_REGISTRY.yaml
- [ ] Other: {artifact_name}

## Deployment Notes
### Environments Tested
- [ ] DEV
- [ ] SIT
- [ ] UAT

### Rollback Plan
{Brief rollback instructions}

### Dependencies
- {Dependency 1}
- {Dependency 2}

## Reviewers
- Tech Lead: @{tech_lead_username}
- Developer: @{developer_username}

## Checklist
- [ ] Code follows secure coding standards (`rules/secure-coding.md`)
- [ ] No hardcoded secrets or PII exposure
- [ ] Tests included and passing
- [ ] Documentation updated
- [ ] AI verification passed
- [ ] KB artifacts updated (if schema/API changes)
- [ ] Rollback plan documented

## Related Links
- Requirement Spec: `context/session/{OWNER}/REQ-{id}/REQ-{id}-SPEC.md`
- Gap Analysis: `context/session/{OWNER}/REQ-{id}/REQ-{id}-GAP-ANALYSIS.md`
- Routing Map: `context/session/{OWNER}/REQ-{id}/REQ-{id}-STORY-{n}-ROUTING.md`
- AI Verification: `context/session/{OWNER}/REQ-{id}/REQ-{id}-STORY-{n}-AI-VERIFICATION.md`

## Approval
- [ ] Code review approved
- [ ] Ready to merge

**Approver**: {Name}  
**Approval Timestamp**: {ISO8601 timestamp}
