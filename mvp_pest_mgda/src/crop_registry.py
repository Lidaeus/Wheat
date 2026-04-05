from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


_DEFAULT_TIMESERIES_METRICS = ("LAID", "LWAD", "SWAD")
_DEFAULT_SUMMARY_AFILE_COLUMNS = (
    ("HWAM", "HWAM"),
    ("HWUM", "HWUM"),
    ("LAIX", "LAIX"),
    ("CWAM", "CWAM"),
    ("ADAP", "ADAT"),
    ("MDAP", "MDAT"),
)
_DEFAULT_OBSERVATION_GROUPS = (
    ("obs_yield", ("hwam_",)),
    ("obs_laix", ("laix_",)),
    ("obs_laid", ("laid_",)),
    ("obs_swad", ("swad_",)),
)
_DEFAULT_GROUPING_PROFILES = (
    ("s1_naive_joint", ("g1_flat_all_in_one", "g3_dssat_extended")),
    ("s2_sequential_phase", ("g1_flat_all_in_one", "g3_dssat_extended")),
    ("s3_wls_joint", ("g3_dssat_extended",)),
)
_DEFAULT_PHASE_TEMPLATES = (
    ("phase0", ("s1_naive_joint", "s2_sequential_phase")),
    ("phase1", ("s1_naive_joint", "s2_sequential_phase")),
    ("phase2", ("s2_sequential_phase", "s3_wls_joint")),
    ("phase3", ("s2_sequential_phase",)),
)
_WHEAT_OBSERVATION_GROUPS = (
    ("obs_phenology", ("adap_", "mdap_", "edap_", "drap_", "tsap_", "idap_", "r8ap_")),
    ("obs_biomass", ("cwam_",)),
    ("obs_canopy", ("laix_", "laid_", "l#sm_")),
    ("obs_yield", ("hwam_",)),
    ("obs_yield_unit_weight", ("hwum_",)),
)
_CABBAGE_OBSERVATION_GROUPS = (
    ("obs_yield", ("pwam_", "pwad_")),
    ("obs_biomass", ("cwad_",)),
    ("obs_laid", ("laid_",)),
)
_CABBAGE_SUMMARY_AFILE_COLUMNS = (
    ("PWAM", "PWAM"),
    ("CWAD", "CWAD"),
)
CROP_PROFILE_SNAPSHOT_FIELDNAMES = (
    "family",
    "display_name",
    "aliases",
    "trial_prefixes",
    "cultivar_file",
    "yield_metric",
    "laix_metric",
    "timeseries_metrics",
    "summary_afile_columns",
    "grouping_profiles",
    "phase_templates",
    "parameter_order",
    "official_bounds_source",
)


@dataclass(frozen=True)
class CropProfile:
    family: str
    display_name: str = ""
    aliases: tuple[str, ...] = ()
    trial_prefixes: tuple[str, ...] = ()
    cultivar_file: str = ""
    yield_metric: str = "HWAM"
    laix_metric: str = "LAIX"
    timeseries_metrics: tuple[str, ...] = _DEFAULT_TIMESERIES_METRICS
    observation_groups: tuple[tuple[str, tuple[str, ...]], ...] = _DEFAULT_OBSERVATION_GROUPS
    summary_afile_columns: tuple[tuple[str, str], ...] = _DEFAULT_SUMMARY_AFILE_COLUMNS
    grouping_profiles: tuple[tuple[str, tuple[str, ...]], ...] = _DEFAULT_GROUPING_PROFILES
    phase_templates: tuple[tuple[str, tuple[str, ...]], ...] = _DEFAULT_PHASE_TEMPLATES
    parameter_order: tuple[str, ...] = ()
    official_bounds_source: str = ""

    def metrics_config(self) -> dict[str, object]:
        return {
            "yield_var": self.yield_metric,
            "laix_var": self.laix_metric,
            "t_vars": list(self.timeseries_metrics),
        }

    def resolved_display_name(self) -> str:
        return str(self.display_name).strip() or self.family.title()

    def observation_groups_config(self) -> dict[str, dict[str, object]]:
        return {
            group_name: {"patterns": list(patterns), "weight": 1.0}
            for group_name, patterns in self.observation_groups
        }

    def summary_afile_column_map(self) -> dict[str, str]:
        return {
            str(metric_code).strip().upper(): str(column_name).strip().upper()
            for metric_code, column_name in self.summary_afile_columns
            if str(metric_code).strip() and str(column_name).strip()
        }

    def compatible_groupings(self, sequence: str) -> tuple[str, ...]:
        normalized_sequence = str(sequence).strip()
        for sequence_name, groupings in self.grouping_profiles:
            if str(sequence_name).strip() == normalized_sequence:
                return tuple(str(grouping).strip() for grouping in groupings if str(grouping).strip())
        return ()

    def phase_template_sequences(self, phase_name: str) -> tuple[str, ...]:
        normalized_phase_name = str(phase_name).strip().lower()
        for template_name, sequences in self.phase_templates:
            if str(template_name).strip().lower() == normalized_phase_name:
                return tuple(str(sequence).strip() for sequence in sequences if str(sequence).strip())
        return ()

    def default_grouping_for_sequence(self, sequence: str) -> str:
        compatible = self.compatible_groupings(sequence)
        if compatible:
            return compatible[-1]
        return "g3_dssat_extended"

    def read_only_snapshot(self) -> dict[str, object]:
        snapshot = {
            "family": self.family,
            "display_name": self.resolved_display_name(),
            "aliases": tuple(iter_crop_aliases(self.family)),
            "trial_prefixes": self.trial_prefixes,
            "cultivar_file": self.cultivar_file,
            "yield_metric": self.yield_metric,
            "laix_metric": self.laix_metric,
            "timeseries_metrics": self.timeseries_metrics,
            "summary_afile_columns": self.summary_afile_columns,
            "grouping_profiles": self.grouping_profiles,
            "phase_templates": self.phase_templates,
            "parameter_order": self.parameter_order,
            "official_bounds_source": self.official_bounds_source,
        }
        return {field_name: snapshot[field_name] for field_name in CROP_PROFILE_SNAPSHOT_FIELDNAMES}


_REGISTERED_PROFILES = (
    CropProfile(
        family="wheat",
        display_name="Wheat",
        aliases=("wheat", "wh"),
        trial_prefixes=("WH",),
        cultivar_file="WHCER048.CUL",
        observation_groups=_WHEAT_OBSERVATION_GROUPS,
        parameter_order=("sh2o_15", "sh2o_30", "p1v", "p1d", "p5", "phint", "g1", "g2", "g3"),
    ),
    CropProfile(
        family="maize",
        display_name="Maize",
        aliases=("maize", "mz", "corn"),
        trial_prefixes=("MZ",),
        cultivar_file="MZCER048.CUL",
    ),
    CropProfile(
        family="rice",
        display_name="Rice",
        aliases=("rice", "ri"),
        trial_prefixes=("RI",),
        cultivar_file="RICER048.CUL",
    ),
    CropProfile(
        family="cabbage",
        display_name="Cabbage",
        aliases=("cabbage", "cb"),
        trial_prefixes=("CB",),
        cultivar_file="CBGRO048.CUL",
        yield_metric="PWAM",
        laix_metric="CWAD",
        timeseries_metrics=("LAID", "CWAD", "PWAD"),
        observation_groups=_CABBAGE_OBSERVATION_GROUPS,
        summary_afile_columns=_CABBAGE_SUMMARY_AFILE_COLUMNS,
    ),
    CropProfile(
        family="cassava",
        display_name="Cassava",
        aliases=("cassava", "cs"),
        trial_prefixes=("CS",),
        cultivar_file="CSCAS048.CUL",
    ),
    CropProfile(
        family="potato",
        display_name="Potato",
        aliases=("potato", "pt"),
        trial_prefixes=("PT",),
        cultivar_file="PTSUB048.CUL",
    ),
    CropProfile(
        family="soybean",
        display_name="Soybean",
        aliases=("soybean", "sb", "soy"),
        trial_prefixes=("SB",),
        cultivar_file="SBGRO048.CUL",
    ),
    CropProfile(
        family="cotton",
        display_name="Cotton",
        aliases=("cotton", "co"),
        trial_prefixes=("CO",),
        cultivar_file="COGRO048.CUL",
    ),
    CropProfile(
        family="sunflower",
        display_name="Sunflower",
        aliases=("sunflower",),
        parameter_order=("ppsen", "sfdur", "slavr", "wtpsd", "xfrt"),
    ),
)

_PROFILE_BY_FAMILY = {profile.family: profile for profile in _REGISTERED_PROFILES}
_FAMILY_BY_ALIAS = {
    alias.lower(): profile.family
    for profile in _REGISTERED_PROFILES
    for alias in (profile.family, *profile.aliases)
    if str(alias).strip()
}
_PROFILE_BY_TRIAL_PREFIX = {
    str(prefix).strip().upper(): profile
    for profile in _REGISTERED_PROFILES
    for prefix in profile.trial_prefixes
    if str(prefix).strip()
}


def _normalize_crop_name(value: object) -> str:
    return str(value).strip().lower()


def resolve_crop_family_name(value: object) -> str:
    normalized = _normalize_crop_name(value)
    if not normalized:
        return ""
    return _FAMILY_BY_ALIAS.get(normalized, normalized)


def resolve_crop_alias(value: object) -> str:
    return resolve_crop_family_name(value)


def get_crop_profile(value: object) -> CropProfile:
    family = resolve_crop_family_name(value)
    if family in _PROFILE_BY_FAMILY:
        return _PROFILE_BY_FAMILY[family]
    return CropProfile(family=family)


def iter_supported_crops() -> tuple[str, ...]:
    return tuple(profile.family for profile in _REGISTERED_PROFILES)


def iter_crop_aliases(value: object) -> tuple[str, ...]:
    profile = get_crop_profile(value)
    ordered_aliases: list[str] = []
    for alias in (profile.family, *profile.aliases):
        normalized = _normalize_crop_name(alias)
        if normalized and normalized not in ordered_aliases:
            ordered_aliases.append(normalized)
    return tuple(ordered_aliases)


def iter_crop_profile_snapshots() -> tuple[dict[str, object], ...]:
    return tuple(profile.read_only_snapshot() for profile in _REGISTERED_PROFILES)


def resolve_crop_profile_from_context(cfg: dict[str, Any] | dict, dssat_dir: Path | None = None) -> CropProfile:
    family = resolve_crop_family_name(cfg.get("crop_family", ""))
    if not family:
        family = resolve_crop_family_name(cfg.get("family", ""))
    if not family:
        params_cfg = cfg.get("params", {}) or {}
        if isinstance(params_cfg, dict):
            family = resolve_crop_family_name(params_cfg.get("family", ""))
    if not family and dssat_dir is not None:
        family = resolve_crop_family_name(dssat_dir.name)
    return get_crop_profile(family)


def resolve_cultivar_file_by_trial_prefix(prefix: str) -> str:
    profile = _PROFILE_BY_TRIAL_PREFIX.get(str(prefix).strip().upper())
    return profile.cultivar_file if profile is not None else ""


def resolve_trial_prefixes(value: object) -> tuple[str, ...]:
    return get_crop_profile(value).trial_prefixes


def resolve_parameter_priority(value: object) -> tuple[str, ...]:
    return get_crop_profile(value).parameter_order


def resolve_groupings_for_sequence(value: object, sequence: str) -> tuple[str, ...]:
    return get_crop_profile(value).compatible_groupings(sequence)


def resolve_phase_template(value: object, phase_name: str) -> tuple[str, ...]:
    return get_crop_profile(value).phase_template_sequences(phase_name)


def resolve_default_grouping(value: object, sequence: str) -> str:
    return get_crop_profile(value).default_grouping_for_sequence(sequence)
