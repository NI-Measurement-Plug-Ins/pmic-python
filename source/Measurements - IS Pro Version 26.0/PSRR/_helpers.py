"""Helper classes and functions for measurement plug-in examples."""

from __future__ import annotations

import logging
import math
import pathlib
from typing import Any, Callable, Sequence, Tuple, TypeVar

import click
import hightime
import nidcpower
import nifgen
import niscope
import numpy as np


def build_log_frequencies(
    freq_start: float, freq_stop: float, points_per_decade: int
) -> np.ndarray:
    """Return log-spaced sweep frequencies with ``points_per_decade`` density."""
    num_decades = math.log10(freq_stop / freq_start)
    num_points = int(round(points_per_decade * num_decades)) + 1
    return np.logspace(math.log10(freq_start), math.log10(freq_stop), num_points)


def configure_source_smu(
    smu: nidcpower.Session, voltage: float, current_limit: float
) -> None:
    """Configure and start an SMU as a DC voltage source."""
    smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    smu.voltage_level_range = voltage
    smu.current_limit_autorange = False
    smu.current_limit_range = current_limit
    smu.current_limit = current_limit
    smu.voltage_level = voltage
    smu.initiate()


def configure_load_smu(
    smu: nidcpower.Session, current: float, voltage_limit: float
) -> None:
    """Configure and start an SMU as a DC current sink (draws ``current``)."""
    smu.output_function = nidcpower.OutputFunction.DC_CURRENT
    smu.current_level_range = current
    smu.voltage_limit_autorange = False
    smu.voltage_limit_range = voltage_limit
    smu.voltage_limit = voltage_limit
    smu.current_level = -current
    smu.initiate()


def setup_fgen(
    fgen: nifgen.Session, load_impedance: float, vpp: float, freq: float
) -> None:
    """Put the FGEN in standard-function mode and start a sine output."""
    fgen.output_mode = nifgen.OutputMode.FUNC
    fgen.load_impedance = load_impedance
    configure_fgen_sine(fgen, vpp, freq)
    fgen.initiate()


def configure_fgen_sine(fgen: nifgen.Session, vpp: float, freq: float) -> None:
    """Set the FGEN sine amplitude and frequency."""
    fgen.configure_standard_waveform(
        waveform=nifgen.Waveform.SINE,
        amplitude=vpp,
        frequency=freq,
        dc_offset=0.0,
    )


def configure_scope_channels(scope: niscope.Session, input_impedance: float) -> None:
    """Set input impedance on both scope channels (Ch0 = Vin, Ch1 = Vout)."""
    for channel in ("0", "1"):
        scope.channels[channel].configure_chan_characteristics(
            input_impedance=input_impedance, max_input_frequency=0.0)


def compute_acquisition_plan(
    freq: float,
    samples_per_cycle: int,
    scope_min_sr: float,
    scope_max_sr: float,
    num_cycles: int,
    min_samples: int,
    max_samples: int,
) -> Tuple[float, int]:
    """Return (sample_rate, num_pts) for a whole number of cycles at ``freq``.

    The record is long enough to average down the noise but bounded so it fits
    onboard memory and the sweep stays quick.
    """
    sample_rate = min(scope_max_sr, max(scope_min_sr, freq * samples_per_cycle))
    cycles = max(num_cycles, int(math.ceil(min_samples * freq / sample_rate)))
    if cycles * sample_rate / freq > max_samples:
        cycles = max(1, int(max_samples * freq / sample_rate))
    num_pts = int(round(cycles * sample_rate / freq))
    return sample_rate, num_pts


def acquire_ripple(
    scope: niscope.Session,
    sample_rate: float,
    num_pts: int,
    vin_range: float,
    vout_range: float,
    probe_atten_in: float,
    probe_atten_out: float,
) -> Tuple[Any, Any]:
    """Configure both channels, acquire, and return the (Vin, Vout) waveforms."""
    scope.channels["0"].configure_vertical(
        range=vin_range, coupling=niscope.VerticalCoupling.AC,
        probe_attenuation=probe_atten_in)
    scope.channels["1"].configure_vertical(
        range=vout_range, coupling=niscope.VerticalCoupling.AC,
        probe_attenuation=probe_atten_out)
    scope.configure_horizontal_timing(
        min_sample_rate=sample_rate, min_num_pts=num_pts,
        ref_position=50.0, num_records=1, enforce_realtime=True)
    timeout = hightime.timedelta(seconds=num_pts / sample_rate + 5.0)
    with scope.initiate():
        w0 = scope.channels["0"].fetch(num_samples=num_pts, timeout=timeout)[0]
        w1 = scope.channels["1"].fetch(num_samples=num_pts, timeout=timeout)[0]
    return w0, w1


def ac_rms(samples: Sequence[float]) -> float:
    """Broadband AC RMS [Vrms] (DC component removed) of the acquired record.

    Diagnostic only: at small ripple levels this is dominated by the scope
    noise/quantization floor, not by the signal.
    """
    x = np.asarray(samples, dtype=float)
    return float(np.sqrt(np.mean((x - x.mean()) ** 2)))


def ac_rms_lockin(samples: Sequence[float], dt: float, freq: float) -> float:
    """Narrowband AC RMS [Vrms] of the component at ``freq``, time domain only.

    Synchronous (lock-in) detection: the record is multiplied by a cosine and a
    sine reference at ``freq`` and averaged. Anything not at ``freq`` averages
    toward zero, so broadband scope noise is rejected. The magnitude
    sqrt(I^2 + Q^2) is phase independent, so FGEN and scope need not be locked.
    """
    x = np.asarray(samples, dtype=float)
    # Trim to a whole number of cycles so the references average exactly to zero.
    samples_per_cycle = 1.0 / (freq * dt)
    n = int(math.floor(x.size / samples_per_cycle) * samples_per_cycle)
    if n < 4:
        n = x.size
    x = x[:n]
    x = x - x.mean()
    phase = 2.0 * math.pi * freq * dt * np.arange(n)
    i_comp = np.mean(x * np.cos(phase))
    q_comp = np.mean(x * np.sin(phase))
    peak = 2.0 * math.hypot(i_comp, q_comp)
    return float(peak / math.sqrt(2.0))


class TestStandSupport:
    """Class that communicates with TestStand."""

    _PIN_MAP_ID_VAR = "NI.MeasurementPlugIns.PinMapId"

    def __init__(self, sequence_context: Any) -> None:
        """Initialize the TestStandSupport object.

        Args:
            sequence_context:
                The SequenceContext COM object from the TestStand sequence execution.
                (Dynamically typed.)
        """
        self._sequence_context = sequence_context

    def get_active_pin_map_id(self) -> str:
        """Get the active pin map id from the NI.MeasurementPlugIns.PinMapId runtime variable.

        Returns:
            The resource id of the pin map if one is registered to the pin map service,
            otherwise an empty string.
        """
        run_time_variables = self._sequence_context.Execution.RunTimeVariables
        if not run_time_variables.Exists(self._PIN_MAP_ID_VAR, 0x0):
            return ""
        return run_time_variables.GetValString(self._PIN_MAP_ID_VAR, 0x0)

    def resolve_file_path(self, file_path: str) -> str:
        """Resolve the absolute path to a file using the TestStand search directories.

        Args:
            file_path:
                An absolute or relative path to the file. If this is a relative path, this function
                searches the TestStand search directories for it.

        Returns:
            The absolute path to the file.
        """
        if pathlib.Path(file_path).is_absolute():
            return file_path
        (_, absolute_path, _, _, user_canceled) = self._sequence_context.Engine.FindFileEx(
            fileToFind=file_path,
            absolutePath=None,
            srchDirType=None,
            searchDirectoryIndex=None,
            userCancelled=None,  # Must match spelling used by TestStand
            searchContext=self._sequence_context.SequenceFile,
        )
        if user_canceled:
            raise RuntimeError("File lookup canceled by user.")
        return absolute_path


def configure_logging(verbosity: int) -> None:
    """Configure logging for this process."""
    if verbosity > 1:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=level)


F = TypeVar("F", bound=Callable)


def verbosity_option(func: F) -> F:
    """Decorator for --verbose command line option."""
    return click.option(
        "-v",
        "--verbose",
        "verbosity",
        count=True,
        help="Enable verbose logging. Repeat to increase verbosity.",
    )(func)
