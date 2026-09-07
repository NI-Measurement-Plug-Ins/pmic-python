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


def create_sweep_frequencies(
    freq_start: float, freq_stop: float, points_per_decade: int, sweep_type: str = "Logarithmic"
) -> np.ndarray:
    """Return sweep frequencies for a ``Linear`` or ``Logarithmic`` sweep.

    Point density is derived from ``points_per_decade`` for both sweep types.
    """
    num_decades = math.log10(freq_stop / freq_start)  # span of the sweep in decades
    num_points = int(round(points_per_decade * num_decades)) + 1  # +1 to include the endpoint
    if sweep_type.strip().lower().startswith("lin"):  # accept "Linear", "lin", etc.
        return np.linspace(freq_start, freq_stop, num_points)  # evenly spaced in frequency
    return np.logspace(math.log10(freq_start), math.log10(freq_stop), num_points)  # spaced in log-f


def configure_source_resource(
    resource: nidcpower.Session, voltage: float, current_limit: float, remote_sense: str = "REMOTE"
) -> None:
    """Configure and start an Source resource as a DC voltage source."""
    resource.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    resource.sense = nidcpower.Sense[remote_sense.strip().upper()]  # LOCAL (2-wire) or REMOTE (4-wire)
    resource.voltage_level_range = voltage
    resource.current_limit_autorange = False  # fixed range for predictable compliance
    resource.current_limit_range = current_limit
    resource.current_limit = current_limit
    resource.voltage_level = voltage
    resource.initiate()  # start sourcing


def configure_load_resource(
    resource: nidcpower.Session, current: float, voltage_limit: float, remote_sense: str = "REMOTE"
) -> None:
    """Configure and start load resource as a DC current sink (draws ``current``)."""
    resource.output_function = nidcpower.OutputFunction.DC_CURRENT
    resource.sense = nidcpower.Sense[remote_sense.strip().upper()]  # LOCAL (2-wire) or REMOTE (4-wire)
    resource.current_level_range = current
    resource.voltage_limit_autorange = False  # fixed range for predictable compliance
    resource.voltage_limit_range = voltage_limit
    resource.voltage_limit = voltage_limit
    if resource.instrument_model == "NI PXIe-4151":  # this model sinks with a positive level
        resource.current_level = current
    else:
        resource.current_level = -current  # sinks current from the DUT
    resource.initiate()  # start sinking


def configure_fgen(
    fgen: nifgen.Session, load_impedance: float, vpp: float, freq: float, channel: str = "0"
) -> None:
    """Put the FGEN in standard-function mode and start a sine output."""
    fgen.output_mode = nifgen.OutputMode.FUNC  # standard-function (sine) generation
    fgen.channels[channel].load_impedance = load_impedance
    configure_fgen_sine(fgen, vpp, freq, channel)
    fgen.initiate()  # start generating


def configure_fgen_sine(
    fgen: nifgen.Session, vpp: float, freq: float, channel: str = "0"
) -> None:
    """Set the FGEN sine amplitude and frequency."""
    fgen.channels[channel].configure_standard_waveform(
        waveform=nifgen.Waveform.SINE,
        amplitude=vpp,
        frequency=freq,
        dc_offset=0.0,
    )


def configure_scope_channels(
    scope: niscope.Session,
    input_impedance: float,
    in_channel: str = "0",
    out_channel: str = "1",
) -> None:
    """Set input impedance on both scope channels (in = Vin, out = Vout)."""
    for channel in (in_channel, out_channel):  # apply to both Vin and Vout channels
        scope.channels[channel].configure_chan_characteristics(
            input_impedance=input_impedance, max_input_frequency=0.0)  # 0 = full channel bandwidth


def compute_acquisition_plan(
    freq: float,
    samples_per_cycle: int,
    scope_min_sr: float,
    scope_max_sr: float,
    num_cycles: int,
) -> Tuple[float, int]:
    """Return (sample_rate, num_pts) for a whole number of cycles at ``freq``."""
    sample_rate = min(scope_max_sr, max(scope_min_sr, freq * samples_per_cycle))  # clamp to scope limits
    num_pts = int(round(num_cycles * sample_rate / freq))  # captures a whole number of cycles
    return sample_rate, num_pts


def acquire_ripple(
    scope: niscope.Session,
    sample_rate: float,
    num_pts: int,
    vin_range: float,
    vout_range: float,
    probe_atten_in: float,
    probe_atten_out: float,
    in_channel: str = "0",
    out_channel: str = "1",
) -> Tuple[Any, Any]:
    """Configure both channels, acquire, and return the (Vin, Vout) waveforms."""
    # AC coupling removes the DC operating point so only ripple is captured.
    scope.channels[in_channel].configure_vertical(
        range=vin_range, coupling=niscope.VerticalCoupling.AC,
        probe_attenuation=probe_atten_in)
    scope.channels[out_channel].configure_vertical(
        range=vout_range, coupling=niscope.VerticalCoupling.AC,
        probe_attenuation=probe_atten_out)
    scope.configure_horizontal_timing(
        min_sample_rate=sample_rate, min_num_pts=num_pts,
        ref_position=50.0, num_records=1, enforce_realtime=True)  # reference centered in the record
    timeout = hightime.timedelta(seconds=num_pts / sample_rate + 5.0)  # record time plus margin
    with scope.initiate():  # arm and acquire
        w0 = scope.channels[in_channel].fetch(num_samples=num_pts, timeout=timeout)[0]  # Vin waveform
        w1 = scope.channels[out_channel].fetch(num_samples=num_pts, timeout=timeout)[0]  # Vout waveform
    return w0, w1


def compute_ac_rms_lockin(samples: Sequence[float], dt: float, freq: float) -> float:
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
    if n < 4:  # too few samples to trim; use the whole record
        n = x.size
    x = x[:n]
    x = x - x.mean()  # remove residual DC before correlation
    phase = 2.0 * math.pi * freq * dt * np.arange(n)
    i_comp = np.mean(x * np.cos(phase))  # in-phase component
    q_comp = np.mean(x * np.sin(phase))  # quadrature component
    peak = 2.0 * math.hypot(i_comp, q_comp)  # amplitude of the tone at ``freq``
    return float(peak / math.sqrt(2.0))  # peak amplitude -> RMS


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
