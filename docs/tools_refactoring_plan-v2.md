# Revised Tool Refactoring Plan

Based on the dev team's feedback, I'll create a more targeted, surgical approach that addresses the specific issues without introducing regressions or unnecessary changes.

## Phase 1: Corrected Approach Principles

### ✅ **Targeted Changes Only**
1. **Add only missing attributes** that are actually needed for base class sanitization
2. **Preserve all existing validation methods** without replacement
3. **Maintain current optimizer behavior** without duplication
4. **No new defaults or behaviors** beyond what's necessary for security

### ✅ **Minimal Integration Pattern**
```python
# Only add these attributes where actually needed
_FLAGS_REQUIRE_VALUE = {
    # Only flags that consume values and aren't already handled
}

_EXTRA_ALLOWED_TOKENS = {
    # Only tokens that actually fail base sanitization
}

# Keep existing validation methods
def _parse_and_validate_args(self, extra_args: str) -> str:
    # Use existing logic, just add base class integration where needed
```

---

## gobuster_tool.py - Targeted Fix

### ✅ **Specific Issues to Address**
1. Add missing `_FLAGS_REQUIRE_VALUE` for proper base class integration
2. Keep existing `_parse_safe_args()` method
3. Preserve all optimizer behavior in `_optimize_mode_args()`

### ✅ **Minimal Changes Required**

```python
# Add these attributes to GobusterTool class
_FLAGS_REQUIRE_VALUE = {
    "-w", "--wordlist", "-t", "--threads", "--timeout",
    "-u", "--url", "-d", "--domain", "-s", "--status-codes",
    "-x", "--extensions", "-o", "--output", "-H", "--header",
    "-c", "--cookies", "-a", "--useragent", "-P", "--password",
    "-U", "--username", "--proxy", "--retry", "--retry-attempts", "--delay"
}

# No _EXTRA_ALLOWED_TOKENS needed - base class already handles these
```

### ✅ **Integration Point**
```python
# Modify _parse_safe_args to use base class for token sanitization
def _parse_safe_args(self, extra_args: str) -> List[str]:
    try:
        # Use base class for initial parsing and sanitization
        sanitized = super()._parse_args(extra_args)
        tokens = shlex.split(sanitized) if sanitized else []
    except ValueError as e:
        raise ValueError(f"Failed to parse arguments: {str(e)}")
    
    # Continue with existing gobuster-specific validation
    validated = []
    # ... rest of existing logic unchanged
```

---

## masscan_tool.py - Targeted Fix

### ✅ **Specific Issues to Address**
1. Add missing `DEFAULT_WAIT = 1` constant
2. Add `_FLAGS_REQUIRE_VALUE` for proper base class integration
3. Keep existing `_parse_and_validate_args()` method
4. Preserve all safety limit behavior

### ✅ **Minimal Changes Required**

```python
# Add missing constant
DEFAULT_WAIT = 1  # Add this to class attributes

# Add these attributes to MasscanTool class
_FLAGS_REQUIRE_VALUE = {
    "-p", "--ports", "--rate", "--max-rate", "--wait",
    "--retries", "--connection-timeout", "--ttl", "--source-port",
    "-e", "--interface", "--source-ip", "--router-ip", "--router-mac",
    "--exclude", "--excludefile", "--adapter-ip", "--adapter-mac"
}

# No _EXTRA_ALLOWED_TOKENS needed - base class already handles these
```

### ✅ **Integration Point**
```python
# Modify _parse_and_validate_args to use base class for token sanitization
def _parse_and_validate_args(self, extra_args: str) -> str:
    try:
        # Use base class for initial parsing and sanitization
        return super()._parse_args(extra_args)
    except ValueError as e:
        # Convert to ToolOutput for consistency
        error_context = ErrorContext(
            error_type=ToolErrorType.VALIDATION_ERROR,
            message=str(e),
            recovery_suggestion="Check masscan arguments and allowed flags",
            timestamp=self._get_timestamp(),
            tool_name=self.tool_name,
            target="",
            metadata={"error": str(e)}
        )
        return self._create_error_output(error_context, "")
```

---

## hydra_tool.py - Targeted Fix

### ✅ **Specific Issues to Address**
1. Add missing type hint to `_setup_enhanced_features()`
2. Add `_FLAGS_REQUIRE_VALUE` for proper base class integration
3. Keep existing `_secure_hydra_args()` method
4. Add error handling to `_secure_hydra_args()`
5. No new defaults or target format changes

### ✅ **Minimal Changes Required**

```python
# Add type hint to existing method
def _setup_enhanced_features(self) -> None:  # Add -> None

# Add these attributes to HydraTool class
_FLAGS_REQUIRE_VALUE = {
    "-l", "-L", "-p", "-P", "-t", "-s", "-T", "-w", "-W",
    "-o", "-m", "/path", "-e", "-C"
}

# No _EXTRA_ALLOWED_TOKENS needed - base class already handles these
```

### ✅ **Integration Point**
```python
# Add error handling to existing _secure_hydra_args method
def _secure_hydra_args(self, extra_args: str) -> str:
    if not extra_args:
        return ""
    
    try:
        # Use base class for initial parsing and sanitization
        sanitized = super()._parse_args(extra_args)
        args = shlex.split(sanitized) if sanitized else []
    except ValueError as e:
        error_context = ErrorContext(
            error_type=ToolErrorType.VALIDATION_ERROR,
            message=f"Failed to parse arguments: {str(e)}",
            recovery_suggestion="Check hydra arguments and allowed flags",
            timestamp=self._get_timestamp(),
            tool_name=self.tool_name,
            target="",
            metadata={"error": str(e)}
        )
        return self._create_error_output(error_context, "")
    
    # Continue with existing hydra-specific logic
    secured = []
    # ... rest of existing logic unchanged
```

---

## sqlmap_tool.py - Targeted Fix

### ✅ **Specific Issues to Address**
1. Add missing `max_threads = 5` attribute
2. Add `_FLAGS_REQUIRE_VALUE` for proper base class integration
3. Keep existing `_secure_sqlmap_args()` method
4. No new defaults or behavior changes

### ✅ **Minimal Changes Required**

```python
# Add missing attribute
max_threads: int = 5  # Add this to class attributes

# Add these attributes to SqlmapTool class
_FLAGS_REQUIRE_VALUE = {
    "-u", "--url", "--risk", "--level", "--technique",
    "--time-sec", "--threads", "--cookie", "--user-agent",
    "--referer", "--headers", "--output-dir", "--union-cols"
}

# No _EXTRA_ALLOWED_TOKENS needed - base class already handles these
```

### ✅ **Integration Point**
```python
# Modify _secure_sqlmap_args to use base class for token sanitization
def _secure_sqlmap_args(self, extra_args: str) -> str:
    if not extra_args:
        return ""
    
    try:
        # Use base class for initial parsing and sanitization
        sanitized = super()._parse_args(extra_args)
        args = shlex.split(sanitized) if sanitized else []
    except ValueError as e:
        raise ValueError(f"Failed to parse arguments: {str(e)}")
    
    # Continue with existing sqlmap-specific logic
    secured = []
    # ... rest of existing logic unchanged
```

---

## Phase 2: Implementation Plan

### ✅ **Step-by-Step Process**

1. **For each tool:**
   - Add missing constants/attributes only
   - Add `_FLAGS_REQUIRE_VALUE` only where needed
   - Modify existing validation methods to use base class sanitization
   - Preserve all existing optimizer behavior
   - Add error handling where missing

2. **Testing Strategy:**
   - Empty extra_args (optimizer defaults only)
   - User-specified flags (no optimizer interference)
   - Mixed user + optimizer (no duplication)
   - Invalid arguments (proper error handling)

3. **Documentation Updates:**
   - Note any security improvements
   - Document any behavior changes (should be minimal)
   - Update usage examples if needed

---

## Phase 3: Validation Checklist

### ✅ **Before Implementation**
- [ ] Review each tool's current validation methods
- [ ] Identify exactly which flags need `_FLAGS_REQUIRE_VALUE`
- [ ] Confirm no new defaults are being introduced
- [ ] Verify existing optimizer behavior is preserved

### ✅ **After Implementation**
- [ ] Test empty extra_args (optimizer only)
- [ ] Test user-specified flags (no duplication)
- [ ] Test mixed scenarios (proper merging)
- [ ] Test error cases (proper handling)
- [ ] Verify no regressions in existing functionality

---

## Ready to Proceed

This revised plan addresses all the dev team's concerns:

1. ✅ **No aggressive default flags** - only adding missing attributes
2. ✅ **Proper use of _parse_and_validate_args()** - minimal integration
3. ✅ **No Hydra target flow conflicts** - preserving existing behavior
4. ✅ **Focused _EXTRA_ALLOWED_TOKENS** - only where actually needed
5. ✅ **No new Hydra behavior** - preserving existing functionality
6. ✅ **Testing and documentation plan** - comprehensive validation

https://chat.z.ai/s/3f2e730f-40a7-42bd-bd77-59fd51288374
