# Task 11 - Decisions

## Design Decisions

1. **Use `_model_or_none` and `_model_list` helpers** instead of inline isinstance checks
   - Keeps read methods clean and consistent
   - Handles all cache-hit (dict) vs cache-miss (model) scenarios uniformly

2. **Removed `list_capabilities_by_server` from implementation**
   - This method would work as a cache layer if it existed in the Protocol
   - But since neither the Protocol nor any storage implementation has it, including it would create dead code
   - Can be added when the Protocol is updated

3. **Removed `("by_server", ...)` invalidation keys** correspondingly
   - Consistent with not caching `list_capabilities_by_server`
