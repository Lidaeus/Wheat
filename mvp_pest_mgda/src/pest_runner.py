from calibration_core import pest_runner as _core_pest_runner


def __getattr__(name: str):
    return getattr(_core_pest_runner, name)


def main() -> None:
    _core_pest_runner.main()


if __name__ == "__main__":
    main()
