# Multi-Environment Validation Playbook

## Purpose
Validate that the Acme Claims agentic system is properly configured for multi-environment AI-IDE support including Devin Cloud, Devin CLI, Windsurf, Cursor, and other AI IDEs.

## Validation Checks

### 1. Path Reference Validation
**Check**: No absolute paths remain in any files
- Search for hardcoded Windows paths (C:\Users\...)
- Search for hardcoded local paths (C:\Users\resource3\...)
- Verify all paths are repository-relative (./, ../)
- Ensure no environment-specific paths in skills/playbooks

**Command**:
```bash
grep -r "C:\Users" --include="*.md" --include="*.json" --include="*.yaml" .
grep -r "C:/Users" --include="*.md" --include="*.json" --include="*.yaml" .
```

**Expected Result**: No matches found

### 2. Configuration Validation
**Check**: Configuration files exist and are properly structured
- Verify `.devin/config.json` exists with base configuration
- Verify `.devin/config.cloud.json` exists for Devin Cloud
- Verify `.devin/config.local.json` exists for local IDEs
- Check path mappings are correct and repository-relative
- Validate JSON syntax of all config files

**Command**:
```bash
cat .devin/config.json
cat .devin/config.cloud.json
cat .devin/config.local.json
```

**Expected Result**: All files exist with valid JSON and correct path mappings

### 3. Session State Strategy Validation
**Check**: Session state management adapts to environment
- Verify session documentation exists and is comprehensive
- Check configuration supports multiple storage strategies
- Validate git workflow documentation is complete
- Ensure session directory structure is correct

**Command**:
```bash
cat sdlc/framework/context/session/README.md
ls -la sdlc/framework/context/session/ "$PWD"/sdlc/framework/context/session/*/
```

**Expected Result**: Documentation exists, session structure is correct

### 4. Skills Validation
**Check**: Skills work in all target environments
- Verify skills use repository-relative paths
- Check skills don't depend on local file system
- Validate skills don't use IDE-specific APIs
- Ensure skills use standard file operations

**Command**:
```bash
find .devin/skills/ -name "*.md" -exec grep -l "C:\Users" {} \;
find .devin/skills/ -name "*.md" -exec grep -l "C:/Users" {} \;
```

**Expected Result**: No matches found

### 5. Git Workflow Validation
**Check**: Git workflow works correctly in all environments
- Verify .gitignore allows necessary files
- Check git workflow documentation is complete
- Validate git credentials are configured
- Ensure branch permissions are correct

**Command**:
```bash
cat .gitignore
git config user.email
git config user.name
```

**Expected Result**: Git is properly configured, .gitignore is correct

### 6. Cross-Platform Compatibility
**Check**: Paths use forward slashes for cross-platform compatibility
- Verify no backslashes in path references
- Check file operations use standard separators
- Validate path resolution works on different OS

**Command**:
```bash
grep -r "\\\\" --include="*.md" --include="*.json" .devin/
```

**Expected Result**: No backslashes in path references (except in comments)

### 7. Environment Detection Validation
**Check**: Configuration resolution works for all environments
- Verify environment detection logic is documented
- Check fallback chain is correct
- Validate default behavior is safe
- Ensure environment variables are supported

**Command**:
```bash
# Check documentation for environment detection
grep -A 10 "Auto-Detection" sdlc/framework/context/session/README.md
```

**Expected Result**: Environment detection is documented and implemented

## Environment-Specific Testing

### Devin Cloud Testing
1. Test with ephemeral VM and fresh code checkout
2. Verify session state commits to git
3. Check git workflow operations work correctly
4. Validate configuration loads correctly

### Devin CLI Testing
1. Test with local development environment
2. Verify session state persists in local file system
3. Check git operations work correctly
4. Validate configuration loads correctly

### Windsurf/Cursor Testing
1. Test with local AI IDE environment
2. Verify cascade chat integration works
3. Check git workflow operations work correctly
4. Validate configuration loads correctly

## Success Criteria

✅ No absolute paths remain in any files
✅ All paths are repository-relative
✅ Configuration resolution works for all environments
✅ Session state strategy adapts to environment
✅ Skills work in all target environments
✅ Git workflow works correctly in all environments
✅ Cross-platform compatibility is maintained
✅ Environment detection is documented and functional

## Failure Remediation

### Path Issues
- Replace absolute paths with repository-relative paths
- Update configuration path mappings
- Fix backslashes to forward slashes

### Configuration Issues
- Create missing configuration files
- Fix JSON syntax errors
- Update path mappings to be repository-relative

### Session State Issues
- Update session documentation
- Fix session directory structure
- Update configuration for correct storage strategy

### Git Workflow Issues
- Update .gitignore to allow necessary files
- Configure git credentials
- Fix branch permissions

## Reporting

Generate validation report with:
- Validation date and time
- Environment tested
- Check results (pass/fail)
- Issues found and remediation steps
- Overall validation status

## Automation

This validation can be automated as part of CI/CD pipeline:
1. Run validation checks on every commit
2. Fail build if validation fails
3. Generate validation report
4. Notify team of validation results
