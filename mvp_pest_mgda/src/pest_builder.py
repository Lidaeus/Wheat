from calibration_core import pest_builder as _core_pest_builder
from calibration_core.pest_builder import (
    apply_observation_configuration,
    apply_parameter_configuration,
    build_pst,
    build_pst_via_script,
    compute_group_weights,
    configure_pst_for_estimation,
    create_pst,
    ensure_parameter_groups,
    run_build_pest_setup,
    run_build_pest_setup_cli,
    resolve_build_pest_setup_script,
    write_pest_output_instruction_file,
)

__all__ = [
    "write_pest_output_instruction_file",
    "resolve_build_pest_setup_script",
    "create_pst",
    "configure_pst_for_estimation",
    "apply_parameter_configuration",
    "ensure_parameter_groups",
    "compute_group_weights",
    "apply_observation_configuration",
    "build_pst",
    "build_pst_via_script",
    "run_build_pest_setup",
    "run_build_pest_setup_cli",
]


def main() -> None:
    _core_pest_builder.main()


if __name__ == "__main__":
    main()
