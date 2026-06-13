# SOP: DOCUMENTATION_HARVEST_v1
# TRIGGER: User requests a new framework, or system identifies a knowledge gap.

## 1. DISCOVERY
- Identify the official documentation URL for the framework/library.
- Check 'knowledge/library/' to see if it's already harvested.

## 2. HARVEST
- Use 'librarian_harvest' to download the core documentation pages.
- Categorize by framework name (e.g. 'pytorch', 'nextjs').

## 3. INDEX
- Wait for Atlas to re-index.
- Use 'atlas_search' to verify the information is now available offline.

## 4. APPLY
- Use the harvested knowledge to solve the user's coding request with higher precision.
