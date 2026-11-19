# Session State Management

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

This directory contains session state for AI-driven SDLC workflows. The session state structure is designed to work across multiple AI development environments.

## Multi-Environment Support

### Target Environments
- **Devin Cloud**: Ephemeral VMs with repository-committed session state
- **Devin CLI**: Local development with local file system storage
- **Windsurf/Cursor**: Local AI IDEs with local file system storage
- **Other AI IDEs**: Universal design for future environments

### Session State Strategy

#### Devin Cloud (Repository-Committed)
- Session state is committed to git for persistence across ephemeral VMs
- Human gate artifacts are version-controlled for full audit trail
- Git workflow: shared `feature/devin-sdlc` branch → explicit owner-scoped staging → commit → push
- Configuration: `.devin/config.cloud.json`

#### Local IDEs (Local File System)
- Session state stored in local file system
- Files persist on local machine between sessions
- No git overhead for session operations
- Configuration: `.devin/config.local.json`

#### Auto-Detection
Skills automatically detect the runtime environment and load appropriate configuration:
1. Check for environment-specific config (config.cloud.json, config.local.json)
2. Fall back to base config (config.json)
3. Use environment variables if available
4. Default to repository-relative paths

## Session Directory Structure

```
context/session/
├── {OWNER}/
│   └── {REQ_ID}/
│       ├── {REQ_ID}-BACKLOG.md
│       ├── {REQ_ID}-JIRA-BACKLOG.yaml
│       ├── {REQ_ID}-GAP-ANALYSIS.md
│       ├── {REQ_ID}-SUBTASK-INSPECTION-REPORT.md
│       ├── approvals.yaml
│       └── session-summary.md
├── REQ-TIN-001/       # legacy, unowned
└── archive/
```

## Git Workflow for Session Management

### Session Start
```bash
git switch feature/devin-sdlc
git pull --rebase
```

### Session Progress
```bash
# After each major milestone; stage only your owner-scoped directory
git add sdlc/framework/context/session/{OWNER}/{REQ_ID}/
git commit -m "Session {REQ_ID}: [Milestone] - [Description]"
git push origin feature/devin-sdlc
```

### Human Gate Artifacts
```bash
# Commit approval files
git add sdlc/framework/context/session/{OWNER}/{REQ_ID}/approvals.yaml
git commit -m "Session {REQ_ID}: Human gate approval - [Gate Name]"
git push origin feature/devin-sdlc
```

### Session Completion
```bash
# Final commit with all artifacts
# Final milestone; stage only your owner-scoped directory
git add sdlc/framework/context/session/{OWNER}/{REQ_ID}/
git commit -m "Session {REQ_ID}: Complete - [Summary]"
git push origin feature/devin-sdlc
```

Never use `git add .` or stage the whole `context/session/` directory. Commit
after each milestone and each gate signature so session state survives ephemeral
VMs and remains isolated from other contributors.

## Configuration Options

### Path Mappings
All paths are repository-relative for cross-platform compatibility:
- `repo_root`: `./`
- `agentic_root`: `./sdlc/framework/`
- `knowledge_base`: `./docs/knowledge-base/`
- `session_context`: `./sdlc/framework/context/session/`
- `templates`: `./.devin/templates/`
- `rules`: `./.devin/rules/`
- `skills`: `./.devin/skills/`
- `agents`: `./.devin/agents/`

### Session State Settings
- `storage_strategy`: "auto" (auto-detect), "repository", or "local"
- `retention_days`: 90 (default session retention period)
- `archive_location`: Path to archived sessions

### Git Workflow Settings
- `branch_strategy`: "shared" (`feature/devin-sdlc`)
- `commit_frequency`: "milestone" (commit after major milestones)
- `push_frequency`: "milestone" (push after major milestones)
- `auto_commit`: true/false (automatic commits)
- `auto_push`: true/false (automatic pushes)
- `shared_branch`: `feature/devin-sdlc`
- `auto_commit` and `auto_push` are declarative settings only; no skill implements them.

### Legacy unscoped sessions

`REQ-TIN-001/`, `REQ-001/`, `TEST-001/`, and `REQ-MULTI-CLIENT-001/` are
legacy, unowned sessions at the session root. Reads check the current owner's
directory first and fall back to these unscoped directories; new sessions are
never written there.

## Migration Guide

### From Local to Cloud
1. Export existing session state from local file system
2. Import to repository structure
3. Update configuration to use repository storage
4. Migrate human gate artifacts to git

### From Cloud to Local
1. Clone repository with session state
2. Update configuration to use local storage
3. Session state will persist in local file system
4. Git operations become optional

## Backup and Recovery

### Repository-Committed Sessions
- Full git history provides automatic backup
- Branch protection prevents accidental deletion
- Git revert/rollback for recovery

### Local File System Sessions
- Regular file system backups recommended
- Session state can be manually archived
- Git integration optional for backup

## Best Practices

1. **Always use repository-relative paths** for cross-platform compatibility
2. **Commit human gate artifacts** for audit trail and team access
3. **Follow consistent naming conventions** for session directories
4. **Archive completed sessions** to maintain clean working directory
5. **Test configuration** in target environment before production use
6. **Document custom configurations** for team members
7. **Use git branches** for session isolation and parallel work
8. **Regular cleanup** of old sessions based on retention policy

## Troubleshooting

### Session State Not Persisting
- Check configuration storage strategy matches environment
- Verify git operations are completing successfully
- Ensure file system permissions are correct

### Path Resolution Issues
- Verify all paths are repository-relative
- Check configuration path mappings are correct
- Ensure working directory is repository root

### Git Workflow Issues
- Verify git credentials are configured
- Check branch permissions on remote repository
- Ensure .gitignore allows session state files

## Support

For issues or questions about session state management:
1. Check this documentation
2. Review configuration files in `.devin/`
3. Consult git workflow documentation
4. Contact team for environment-specific issues
