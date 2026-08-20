"""PSRR (Power Supply Rejection Ratio) measurement plug-in.

Source = DC voltage source -> DUT Vin
Load   = DC current sink   -> load
FGEN = sine injection    -> line injector -> DUT Vin
SCOPE= NI 5162, Ch0 = Vin ripple, Ch1 = Vout ripple

PSRR(f) = 20 * log10( Vout_ripple / Vin_ripple )   [dB]

Results are streamed as arrays and graphed directly in InstrumentStudio
(no matplotlib).
"""

import logging
import math
import pathlib
import sys
import time
from typing import Generator, Tuple

import click
import ni_measurement_plugin_sdk_service as nims
import nidcpower
import nifgen
import niscope
import numpy as np

from _helpers import (
    ac_rms,
    ac_rms_lockin,
    acquire_ripple,
    build_log_frequencies,
    compute_acquisition_plan,
    configure_fgen_sine,
    configure_load_smu,
    configure_scope_channels,
    configure_source_smu,
    setup_fgen,
)

_logger = logging.getLogger(__name__)

script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(
    service_config_path=service_directory / "PSRR.serviceconfig",
    ui_file_paths=[service_directory / "PSRR.measui"],
)


@measurement_service.register_measurement
# Source
@measurement_service.configuration("Source resource name", nims.DataType.String, "NISMU1")
@measurement_service.configuration("Source voltage Vin (V)", nims.DataType.Double, 20.0)
@measurement_service.configuration("Source current limit (A)", nims.DataType.Double, 0.5)
# Load
@measurement_service.configuration("Load resource name", nims.DataType.String, "NISMU2")
@measurement_service.configuration("Load current Iload (A)", nims.DataType.Double, 0.050)
@measurement_service.configuration("Load voltage limit (V)", nims.DataType.Double, 5.0)
@measurement_service.configuration("Vout expected (V)", nims.DataType.Double, 3.3)
# FGEN / injection sweep
@measurement_service.configuration("FGEN", nims.DataType.String, "NIFGEN")
@measurement_service.configuration("FGEN load impedance (Ohm)", nims.DataType.Double, 1.0e6)
@measurement_service.configuration("Inject Vpp (V)", nims.DataType.Double, 1.0)
@measurement_service.configuration("Freq start (Hz)", nims.DataType.Double, 10.0)
@measurement_service.configuration("Freq stop (Hz)", nims.DataType.Double, 10.0e6)
@measurement_service.configuration("Points per decade", nims.DataType.Int32, 8)
@measurement_service.configuration("Settle time (s)", nims.DataType.Double, 1.0)
# Scope
@measurement_service.configuration("Scope", nims.DataType.String, "NISCOPE1")
@measurement_service.configuration("Samples per cycle", nims.DataType.Int32, 100_000)
@measurement_service.configuration("Num cycles", nims.DataType.Int32, 8)
@measurement_service.configuration("Min samples", nims.DataType.Int32, 100_000)
@measurement_service.configuration("Max samples", nims.DataType.Int32, 500_000)
@measurement_service.configuration("Scope max sample rate", nims.DataType.Double, 100.0e6)
@measurement_service.configuration("Scope min sample rate", nims.DataType.Double, 1.0e2)
@measurement_service.configuration("Scope input impedance (Ohm)", nims.DataType.Double, 1.0e6)
@measurement_service.configuration("Scope probe atten Vin", nims.DataType.Double, 10.0)
@measurement_service.configuration("Scope probe atten Vout", nims.DataType.Double, 10.0)
@measurement_service.configuration("Vout range (V)", nims.DataType.Double, 0.05)
# Outputs
@measurement_service.output("Status", nims.DataType.String)
@measurement_service.output("Frequency (Hz)", nims.DataType.DoubleArray1D)
@measurement_service.output("PSRR (dB)", nims.DataType.DoubleArray1D)
@measurement_service.output("Vin ripple (Vrms)", nims.DataType.DoubleArray1D)
@measurement_service.output("Vout ripple (Vrms)", nims.DataType.DoubleArray1D)
def measure(
    source_resource_name: str,
    vin: float,
    source_current_limit: float,
    load_resource_name: str,
    iload: float,
    load_voltage_limit: float,
    vout_expected: float,
    fgen_resource: str,
    fgen_load_impedance: float,
    inject_vpp: float,
    freq_start: float,
    freq_stop: float,
    points_per_decade: int,
    settle_s: float,
    scope_resource: str,
    samples_per_cycle: int,
    num_cycles: int,
    min_samples: int,
    max_samples: int,
    scope_max_sr: float,
    scope_min_sr: float,
    scope_input_z: float,
    scope_probe_atten_in: float,
    scope_probe_atten_out: float,
    vout_range: float,
) -> Generator[Tuple, None, Tuple]:
    """Sweep the injection frequency and compute PSRR at each point."""
    # Outputs
    status: str = ""
    freq_out: list[float] = []
    psrr_out: list[float] = []
    vin_out: list[float] = []
    vout_out: list[float] = []

    num_decades = math.log10(freq_stop / freq_start)
    num_points = int(round(points_per_decade * num_decades)) + 1
    freqs = build_log_frequencies(freq_start, freq_stop, points_per_decade)
    vin_amps = np.full(num_points, np.nan)
    vout_amps = np.full(num_points, np.nan)

    source_session = nidcpower.Session(resource_name=source_resource_name)
    load_session = nidcpower.Session(resource_name=load_resource_name)
    fgen = nifgen.Session(resource_name=fgen_resource)
    scope = niscope.Session(resource_name=scope_resource)

    try:
        # --- Source: DC voltage source ---
        configure_source_smu(source_session, vin, source_current_limit)

        # --- FGEN: sine at first frequency ---
        setup_fgen(fgen, fgen_load_impedance, inject_vpp, freq_start)

        # --- Load: DC current sink ---
        configure_load_smu(load_session, iload, load_voltage_limit)

        # --- Scope channel characteristics (Ch0 = Vin, Ch1 = Vout) ---
        configure_scope_channels(scope, scope_input_z)

        # --- DC pre-check ---
        time.sleep(0.2)
        m1 = source_session.measure_multiple()[0]
        m2 = load_session.measure_multiple()[0]
        _logger.info("DC pre-check: Vin set=%.3f V meas=%.3f V Iin=%.1f mA",
                     vin, m1.voltage, m1.current * 1e3)
        _logger.info("DC pre-check: Vout exp=%.3f V meas=%.3f V Iload=%.1f mA",
                     vout_expected, m2.voltage, abs(m2.current) * 1e3)
        if abs(m1.voltage - vin) > 0.1:
            _logger.warning("Vin out of tolerance")
        if abs(m2.voltage - vout_expected) > 0.25:
            _logger.warning("Vout out of tolerance")

        # Input channel vertical range ~ injection level
        vin_range = max(2.0 * inject_vpp, 0.05)

        # --- Frequency sweep ---
        for i, f in enumerate(freqs):
            configure_fgen_sine(fgen, inject_vpp, f)
            time.sleep(settle_s)

            sample_rate, num_pts = compute_acquisition_plan(
                f, samples_per_cycle, scope_min_sr, scope_max_sr,
                num_cycles, min_samples, max_samples)

            w0, w1 = acquire_ripple(
                scope, sample_rate, num_pts, vin_range, vout_range,
                scope_probe_atten_in, scope_probe_atten_out)

            # Actual (coerced) sample interval, needed for a correct reference phase.
            dt = w1.x_increment
            vin_amps[i] = ac_rms_lockin(w0.samples, dt, f)
            vout_amps[i] = ac_rms_lockin(w1.samples, dt, f)
            vout_floor = ac_rms(w1.samples)  # broadband floor, for margin check

            psrr = abs(20.0 * math.log10(vout_amps[i] / vin_amps[i]))
            margin_db = (20.0 * math.log10(vout_amps[i] / vout_floor)
                         if vout_floor > 0 else 0.0)
            flag = "  <-- near noise floor" if margin_db < -6.0 else ""
            _logger.info(
                "[%3d/%d] f=%12.1f Hz  Vin=%8.3f mVrms  Vout=%10.3f uVrms  "
                "PSRR=%7.2f dB  (floor=%9.1f uVrms)%s",
                i + 1, num_points, f, vin_amps[i] * 1e3, vout_amps[i] * 1e6,
                psrr, vout_floor * 1e6, flag)

            # Stream the results collected so far so InstrumentStudio updates live.
            status = f"Sweeping {i + 1}/{num_points} ({f:.1f} Hz)"
            freq_out = freqs[: i + 1].tolist()
            psrr_out = np.abs(20.0 * np.log10(vout_amps[: i + 1] / vin_amps[: i + 1])).tolist()
            vin_out = vin_amps[: i + 1].tolist()
            vout_out = vout_amps[: i + 1].tolist()
            yield (status, freq_out, psrr_out, vin_out, vout_out)

    finally:
        fgen.abort()
        fgen.close()
        scope.close()
        load_session.output_enabled = False
        load_session.abort()
        load_session.close()
        source_session.output_enabled = False
        source_session.abort()
        source_session.close()

    status = "The measurement is performed successfully"
    return (status, freq_out, psrr_out, vin_out, vout_out)


@click.command
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable verbose logging. Repeat to increase verbosity.",
)
def main(verbose: int) -> None:
    """Host the PSRR service."""
    if verbose > 1:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=level)

    with measurement_service.host_service():
        input("Press enter to close the measurement service.\n")


if __name__ == "__main__":
    main()
