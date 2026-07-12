## Challenge Summary

**Overall risk assessment**: LOW

All standard boundary cases and deduplication scenarios successfully passed our test suite. We have uncovered a few edge cases where the logic relies on assumptions that could lead to false negatives if a parameter is set to `0` or if the THP status is spoofed.

---

## Challenges

### [Low] Challenge 1: `vm.max_map_count` of 0
- **Assumption challenged**: `vm.max_map_count` is always greater than `0`.
- **Attack scenario**: If a misconfigured system has `vm.max_map_count = 0`, the checker `if max_map and max_map < 1_000_000_000` evaluates `0` as falsy and does NOT trigger the critical finding, resulting in a false negative.
- **Blast radius**: Low. Real-world systems rarely set `max_map_count` to exactly 0, but if they do, the system will crash and no alert will be raised by this checker.
- **Mitigation**: Update the condition in `superchecker.py` to `if max_map is not None and max_map < 1_000_000_000` (and similarly for the memory pressure path `if mmc < 1_000_000_000`).

### [Low] Challenge 2: `net.core.somaxconn` of 0
- **Assumption challenged**: `net.core.somaxconn` is always positive.
- **Attack scenario**: If `somaxconn` is set to `0`, `if somax and somax < 1024` evaluates to False because `somax` (0.0) is falsy. The warning will not fire.
- **Blast radius**: Low.
- **Mitigation**: Update condition to `if somax is not None and somax < 1024`.

### [Low] Challenge 3: THP status override
- **Assumption challenged**: `status == "disabled"` implies that both `enabled` and `defrag` are indeed disabled (`never`).
- **Attack scenario**: If the report contains `status: "disabled"` but the raw fields `active: "always"` and `active_defrag: "always"` are set, the checker `is_enabled_never = ... or thp.get("status") == "disabled"` evaluates to `True` for both. The critical finding will be bypassed despite THP actually being active on the node.
- **Blast radius**: Low. This would only occur if the parsing/aggregation step incorrectly sets status or the input report is manually manipulated/corrupted.
- **Mitigation**: Only check `thp.get("status") == "disabled"` as a fallback when granular fields are missing, or validate consistency.

---

## Stress Test Results

- `vm.swappiness` values in `[1, 10]` → No warning → **Pass**
- `vm.swappiness` values `< 1` or `> 10` (e.g. `0`, `11`, `60`) → Warning fired → **Pass**
- `vm.max_map_count` values `>= 1,000,000,000` → No warning → **Pass**
- `vm.max_map_count` values `< 1,000,000,000` (e.g. `999,999,999`) → Critical finding fired → **Pass**
- `transparentHugepage` when both enabled and defrag are `never` (or status disabled) → No warning → **Pass**
- `transparentHugepage` when either enabled or defrag is not `never` (e.g. `always`) → Critical finding fired → **Pass**
- `net.core.somaxconn` `>= 1024` → No warning → **Pass**
- `net.core.somaxconn` `< 1024` (e.g. `1023`) → Warning fired → **Pass**
- `_add_unique` deduplication with identical checker_id and nodes → Retains exactly 1 finding → **Pass**
- `_add_unique` deduplication with same checker_id/nodes but longer evidence → Updates finding with longer evidence → **Pass**
- `_add_unique` deduplication with same checker_id/nodes but shorter evidence → Retains the longer evidence → **Pass**
- `_add_unique` with different nodes list → Retains both findings separately → **Pass**

---

## Unchallenged Areas

- Other kernel parameters (e.g. `wmem_max`, `rmem_max`, `overcommit_memory`) — reason not challenged: outside the direct scope of the requested boundary check list.
