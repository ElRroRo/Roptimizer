"""v4.1's jump calibration module, kept so old imports keep working (v5.0, build slice 1).

The calibration now lives in mso.jumpdb and runs only when asked (`python -m mso jumpdb recalibrate`,
or the GUI's Recalibrate), never at import. JUMP_CONFIG, HAWKES_CONFIG and COJUMP_CONFIG here are the
newest stored version's, read from jumpdb/ on first use; with no version stored they raise, naming the
command that makes one.
"""
from mso.jumpdb import (baseline_for_mean_rate, calibrate, calibrate_cojump_multiplier,  # noqa: F401
                        calibrate_hawkes_from_indicators, calibrate_regimes_direct, get_scaled_jump_config,
                        plot_regimes_side_by_side)

_NAMES = {"JUMP_CONFIG": "jump_config", "HAWKES_CONFIG": "hawkes_config", "COJUMP_CONFIG": "cojump_config"}


def __getattr__(name):
    if name in _NAMES:
        from mso import jumpdb
        return jumpdb.load("latest")[_NAMES[name]]
    raise AttributeError(name)
