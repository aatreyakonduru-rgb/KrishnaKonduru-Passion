# Routing Map: {STORY-ID} ({Story Title})

## Story Summary
{Brief description from backlog}

## Affected Layers
- [ ] Database Layer
- [ ] API Layer
- [ ] UI / Presentation Layer
- [ ] Data Processing Layer (ETL)
- [ ] Business Logic Layer
- [ ] Integration Layer
- [ ] Infrastructure Layer
- [ ] Testing Layer

## Affected Files
| File Path | File Type | Change Type | Owner |
|-----------|-----------|-------------|-------|
| {file_path} | {new/existing} | {add/modify/delete} | {developer_name} |
| {file_path} | {new/existing} | {add/modify/delete} | {developer_name} |

## Dependency Order
1. {First change (typically DB)}
2. {Second change (typically API)}
3. {Third change (typically UI)}
...

## Branch Strategy
{Single branch vs. multi-branch}

**Branch Name**: `feature/REQ-{id}-STORY-{n}-{description}`

## Rollback Plan
### Rollback Steps
1. {Rollback step 1}
2. {Rollback step 2}
...

### Rollback Tested
- [ ] Tested in DEV
- [ ] Rollback time estimate: {duration}

### Rollback Triggers
- {Trigger 1}
- {Trigger 2}

## Feature Flag
- [ ] Feature flag required (if prod mutation)
- [ ] No feature flag needed (additive change)

**Flag Name** (if applicable): `feature_{requirement_id}_{story_id}`

## Change Owner
{Role}: {Name}

## Coding Patterns
- {Pattern 1}: {Description}
- {Pattern 2}: {Description}

## Dependencies
- {Dependency 1} (must be completed before {Dependency 2})
- {Dependency 2}

## Risks
- {Risk 1}: {Mitigation}
- {Risk 2}: {Mitigation}

## Approver
Tech Lead: {Name}

## Approval Timestamp
{ISO8601 timestamp}

## Next Phase
Implement (Code Generation, Dev Environment Testing)
