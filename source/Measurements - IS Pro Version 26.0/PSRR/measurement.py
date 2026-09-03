"""PSRR (Power Supply Rejection Ratio) measurement plug-in.

PSRR is a measure of how well a device rejects ripple/noise on its power
supply input, expressed as the ratio of input supply ripple to the resulting
output ripple. A higher PSRR (in dB) means better rejection of supply noise.

Instruments used:
Source = DC voltage source -> DUT Vin
Load   = DC current sink   -> load
FGEN = sine injection    -> line injector -> DUT Vin
SCOPE= for measuring ripple, Ch0 = Vin ripple, Ch1 = Vout ripple

PSRR(f) = 20 * log10( Vout_ripple / Vin_ripple )   [dB]

Results are streamed as arrays and graphed directly in InstrumentStudio

"""

import logging                      # For logging messages to console and log file
import math                         # For math functions
import pathlib                      # For filesystem path manipulations
import sys                          # For sys.executable and sys.frozen
import time                         # For time.sleep() to wait for settling
from typing import Generator, Tuple # For type hinting of generator return values

# Third-party and instrument driver imports
import click
import ni_measurement_plugin_sdk_service as nims #
import nidcpower      # For controlling source and load
import nifgen         # For controlling function generator 
import niscope        # For controlling oscilloscope for ripple capture
import numpy as np    # For numeric array processing

from _helpers import (
    compute_ac_rms,
    compute_ac_rms_lockin,
    acquire_ripple,
    compute_acquisition_plan,
    configure_fgen_sine,
    configure_load_resource,
    configure_scope_channels,
    configure_source_resource,
    create_sweep_frequencies,
    configure_fgen,
)

_logger = logging.getLogger(__name__)

script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(
    service_config_path=service_directory / "PSRR.serviceconfig",
    ui_file_paths=[service_directory / "PSRR.measui"],
)


@measurement_service.register_measurement
#DUT Configuration
@measurement_service.configuration("Nominal output voltage", nims.DataType.Double, 3.3)
# Source Configuration
@measurement_service.configuration("Source resource name", nims.DataType.String, "NISMU1")
@measurement_service.configuration("Source voltage level", nims.DataType.Double, 20.0)
@measurement_service.configuration("Source current limit", nims.DataType.Double, 0.5)
@measurement_service.configuration("Source remote sense", nims.DataType.String, "Remote")
# Load Configuration
@measurement_service.configuration("Load resource name", nims.DataType.String, "NISMU2")
@measurement_service.configuration("Load current level", nims.DataType.Double, 0.050)
@measurement_service.configuration("Load voltage limit", nims.DataType.Double, 5.0)
@measurement_service.configuration("Load remote sense", nims.DataType.String, "Remote")
# FGEN Configuration
@measurement_service.configuration("FGEN resource name", nims.DataType.String, "NIFGEN")
@measurement_service.configuration("FGEN load impedance", nims.DataType.Double, 1.0e6)
@measurement_service.configuration("FGEN pk-pk amplitude", nims.DataType.Double, 1.0)
@measurement_service.configuration("FGEN start frequency", nims.DataType.Double, 10.0)
@measurement_service.configuration("FGEN stop frequency", nims.DataType.Double, 10.0e6)
@measurement_service.configuration("FGEN sweep type", nims.DataType.String, "Logarithmic")
@measurement_service.configuration("FGEN points or points per decade", nims.DataType.Int32, 8)
@measurement_service.configuration("FGEN settle time", nims.DataType.Double, 1.0)
# Scope Configuration
@measurement_service.configuration("Scope resource name", nims.DataType.String, "NISCOPE1")
@measurement_service.configuration("Scope input channel", nims.DataType.String, "0")
@measurement_service.configuration("Scope output channel", nims.DataType.String, "1")
@measurement_service.configuration("Scope samples per cycle", nims.DataType.Int32, 100_000)
@measurement_service.configuration("Scope number of cycles", nims.DataType.Int32, 8)
@measurement_service.configuration("Scope maximum sample rate", nims.DataType.Double, 100.0e6)
@measurement_service.configuration("Scope minimum sample rate", nims.DataType.Double, 1.0e2)
@measurement_service.configuration("Scope input impedance", nims.DataType.Double, 1.0e6)
@measurement_service.configuration("Scope probe attenuation Vin", nims.DataType.Double, 10.0)
@measurement_service.configuration("Scope probe attenuation Vout", nims.DataType.Double, 10.0)
@measurement_service.configuration("Scope vout range", nims.DataType.Double, 0.05)
# Outputs
@measurement_service.output("Status", nims.DataType.String)
@measurement_service.output("Frequency (Hz)", nims.DataType.DoubleArray1D)
@measurement_service.output("PSRR (dB)", nims.DataType.DoubleArray1D)

def measure(
    nominal_output_voltage: float,
    source_resource_name: str,
    source_voltage_level: float,
    source_current_limit: float,
    source_remote_sense: str,
    load_resource_name: str,
    load_current_level: float,
    load_voltage_limit: float,
    load_remote_sense: str,
    fgen_resource_name: str,
    fgen_load_impedance: float,
    fgen_pk_pk_amplitude: float,
    fgen_start_frequency: float,
    fgen_stop_frequency: float,
    fgen_sweep_type: str,
    fgen_points_per_decade: int,
    fgen_settle_time: float,
    scope_resource_name: str,
    scope_input_channel: str,
    scope_output_channel: str,
    scope_samples_per_cycle: int,
    scope_number_of_cycles: int,
    scope_maximum_sample_rate: float,
    scope_minimum_sample_rate: float,
    scope_input_impedance: float,
    scope_probe_attenuation_vin: float,
    scope_probe_attenuation_vout: float,
    scope_vout_range: float,
) -> Generator[Tuple, None, Tuple]:
    """Sweep the injection frequency and compute PSRR at each point."""
    # Outputs
    status: str = ""             # Status message for the measurement service
    freq_out: list[float] = []   # Frequencies at which PSRR was measured
    psrr_out: list[float] = []   #PSRR values corresponding to the frequencies in freq_out
    vin_out: list[float] = []    #Vin ripple values corresponding to the frequencies in freq_out
    vout_out: list[float] = []   #Vout ripple values corresponding to the frequencies in freq_out

    freqs = create_sweep_frequencies(
        fgen_start_frequency, fgen_stop_frequency, fgen_points_per_decade, fgen_sweep_type)
    num_points = len(freqs)                    # Number of frequency points to sweep
    vin_ripple = np.full(num_points, np.nan)   # Vin ripple values corresponding to the frequencies in freqs
    vout_ripple = np.full(num_points, np.nan)  # Vout ripple values corresponding to the frequencies in freqs

    source_session = nidcpower.Session(resource_name=source_resource_name) # Create a session for the source instrument
    load_session = nidcpower.Session(resource_name=load_resource_name) # Create a session for the load instrument
    fgen = nifgen.Session(resource_name=fgen_resource_name) # Create a session for the function generator
    scope = niscope.Session(resource_name=scope_resource_name) # Create a session for the oscilloscope

    try:
        # Source: DC voltage source
        configure_source_resource(
            source_session, source_voltage_level, source_current_limit, source_remote_sense)

        # FGEN: sine at first frequency
        configure_fgen(fgen, fgen_load_impedance, fgen_pk_pk_amplitude, fgen_start_frequency)

        # Load: DC current sink
        configure_load_resource(
            load_session, load_current_level, load_voltage_limit, load_remote_sense)

        # Scope channel characteristics (in = Vin, out = Vout)
        configure_scope_channels(
            scope, scope_input_impedance, scope_input_channel, scope_output_channel)

        # DC pre-check of Vin and Vout before starting the frequency sweep
        time.sleep(0.2)
        m1 = source_session.measure_multiple()[0]
        m2 = load_session.measure_multiple()[0]
        _logger.info("DC pre-check: Vin set=%.3f V meas=%.3f V Iin=%.1f mA",
                     source_voltage_level, m1.voltage, m1.current * 1e3)
        _logger.info("DC pre-check: Vout exp=%.3f V meas=%.3f V Iload=%.1f mA",
                     nominal_output_voltage, m2.voltage, abs(m2.current) * 1e3)
        if abs(m1.voltage - source_voltage_level) > 0.1:
            _logger.warning("Vin out of tolerance")
        if abs(m2.voltage - nominal_output_voltage) > 0.25:
            _logger.warning("Vout out of tolerance")

        # Input channel vertical range ~ injection level
        vin_range = max(2.0 * fgen_pk_pk_amplitude, 0.05)

        # Frequency sweep 
        for i, f in enumerate(freqs):
            configure_fgen_sine(fgen, fgen_pk_pk_amplitude, f)
            time.sleep(fgen_settle_time)
            # Compute the sample rate and number of points for the scope acquisition
            sample_rate, num_pts = compute_acquisition_plan(
                f, scope_samples_per_cycle, scope_minimum_sample_rate,
                scope_maximum_sample_rate, scope_number_of_cycles)
            # Acquire Vin and Vout ripple at the current frequency
            w0, w1 = acquire_ripple(
                scope, sample_rate, num_pts, vin_range, scope_vout_range,
                scope_probe_attenuation_vin, scope_probe_attenuation_vout,
                scope_input_channel, scope_output_channel)

            # Actual (coerced) sample interval, needed for a correct reference phase.
            dt = w1.x_increment
            # Narrowband lock-in RMS of the ripple at the injection frequency
            vin_ripple[i] = compute_ac_rms_lockin(w0.samples, dt, f)
            vout_ripple[i] = compute_ac_rms_lockin(w1.samples, dt, f)
            vout_floor = compute_ac_rms(w1.samples)                   # broadband floor, for margin check

            # PSRR in dB from the input/output ripple ratio
            psrr = abs(20.0 * math.log10(vout_ripple[i] / vin_ripple[i]))
            # Per-point diagnostic log line
            _logger.info(
                "[%3d/%d] f=%12.1f Hz  Vin=%8.3f mVrms  Vout=%10.3f uVrms  "
                "PSRR=%7.2f dB  (floor=%9.1f uVrms)",
                i + 1, num_points, f, vin_ripple[i] * 1e3, vout_ripple[i] * 1e6,
                psrr, vout_floor * 1e6)

            # Stream the results collected so far so InstrumentStudio updates live.
            status = f"Sweeping {i + 1}/{num_points} ({f:.1f} Hz)"
            freq_out = freqs[: i + 1].tolist()
            psrr_out = np.abs(20.0 * np.log10(vout_ripple[: i + 1] / vin_ripple[: i + 1])).tolist()
            vin_out = vin_ripple[: i + 1].tolist()
            vout_out = vout_ripple[: i + 1].tolist()
            yield (status, freq_out, psrr_out, vin_out, vout_out)

    finally:
        fgen.abort()                            # Stop the function generator output
        fgen.close()                            # Close the function generator session
        scope.close()                           # Close the oscilloscope session
        load_session.output_enabled = False     # Disable the load output
        load_session.abort()                    # Abort the load session
        load_session.close()                    # Close the load session
        source_session.output_enabled = False   # Disable the source output
        source_session.abort()                  # Abort the source session
        source_session.close()                  # Close the source session

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
