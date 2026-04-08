# DSSAT cultivar runtime fix

## Summary

- Fixed wheat `.CUL` parameter writing to use a stable DSSAT fixed-width numeric template for `P1V`, `P1D`, `P5`, `G1`, `G2`, `G3`, and `PHINT`
- Switched the short-term cultivar write target back to the DSSAT root genotype file that DSSAT actually reads during execution
- Kept the cultivar file lock in place so the short-term correctness fix remains serialized and safe

## Root cause

### 1. `rewrite_cul_values()` corrupted the cultivar row

The previous implementation inferred replacement width from current token spans and truncated overflowing values. For wheat cultivars this produced malformed rows such as merged or shifted fields, which either:

- silently flattened parameter sensitivity, or
- triggered DSSAT `Invalid format in file ... Error key: IPVAR`

### 2. Runtime-isolated `.dssat_rt` cultivar copies were not the effective DSSAT read path

The execution path updated a runtime copy of `WHCER048.CUL`, but targeted verification showed that DSSAT sensitivity only returned when the root genotype file was edited directly.

## Code changes

### `mvp_pest_mgda/src/dssat_io.py`

- Added a fixed-width numeric formatter for:
  - `P1V` -> width 6, precision 3
  - `P1D` -> width 6, precision 2
  - `P5` -> width 6, precision 1
  - `G1` -> width 6, precision 2
  - `G2` -> width 6, precision 2
  - `G3` -> width 6, precision 3
  - `PHINT` -> width 6, precision 2
- Removed silent truncation behavior for rewritten values
- Kept a narrower fallback formatter only for non-template columns

### `mvp_pest_mgda/src/run_model.py`

- Routed cultivar writes back to the resolved DSSAT root genotype file
- Patched case support directories against the same root genotype directory
- Preserved the cultivar lock so concurrent workers do not write the root cultivar simultaneously

## Verification

### Targeted sensitivity check

Using the existing `W2_O2_S2_G3` runtime workspace:

- low setting: `G2=35`, `G3=1.1`, `PHINT=80`
- high setting: `G2=75`, `G3=2.9`, `PHINT=167`

Result:

- both runs completed successfully
- `pest_out.dat` changed
- first observed difference appeared at `laix_t01`

This verifies that parameter changes once again propagate into DSSAT output.

## Merge notes

- This bugfix should be merged together with any branch that modifies DSSAT cultivar writing or runtime path isolation
- If another branch also touched `rewrite_cul_values()` or runtime genotype routing, prefer this fixed-width writer and re-evaluate long-term runtime isolation separately
- The current root-file approach is a short-term correctness fix; a future branch can restore parallel runtime isolation only after confirming DSSAT reads the isolated genotype path
