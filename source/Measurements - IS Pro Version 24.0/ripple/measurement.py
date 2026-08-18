import sys
from enum import Enum

import ni_measurementlink_service as nims
from _helpers import *

from configure_dcpower import *
from configure_niscope_acquisition import *
import numpy as np


class ModeOfOperation(Enum):
    power_on_dut = 0
    perform_measurement = 1
    power_off_dut = 2
    pass


def calculate_pk_to_pk(signal):
    return np.max(signal) - np.min(signal)


def calculate_rms(signal):
    return np.sqrt(np.mean(np.square(signal)))


def format_dut_info(status, voltage, current):
    return "The DUT is powered %s\nVoltage Level: %.3f V\nCurrent Limit: %.3f A" % (status, voltage, current)


script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(
    service_config_path=service_directory / "Ripple_PMIC.serviceconfig",
    version="0.1.0.0",
    ui_file_paths=[service_directory / "Ripple_PMIC.measui"],
)


@measurement_service.register_measurement
# On-Off feature
@measurement_service.configuration("Mode of operation", nims.DataType.Enum,
                                   default_value=ModeOfOperation.perform_measurement, enum_type=ModeOfOperation)
@measurement_service.configuration("DUT setup time (s)", nims.DataType.Float, 1.0)
@measurement_service.configuration("Aperture time (s)", nims.DataType.Float, 0.005)
@measurement_service.configuration("Source resource name", nims.DataType.String, 'PPS')
@measurement_service.configuration("Source voltage level (V)", nims.DataType.Float, 10.0)
@measurement_service.configuration("Source current limit (A)", nims.DataType.Float, 15.0)
@measurement_service.configuration("Load resource name", nims.DataType.String, 'E-load')
@measurement_service.configuration("Load current level (A)", nims.DataType.Float, 1.0)
@measurement_service.configuration("Load voltage limit range (V)", nims.DataType.Float, 6.0)
@measurement_service.configuration("Scope resource name", nims.DataType.String, 'Scope')
@measurement_service.configuration("Scope channel name", nims.DataType.String, '0')
@measurement_service.configuration("Sample rate (Hz)", nims.DataType.Double, 10000.0)
@measurement_service.configuration("Acquisition time (s)", nims.DataType.Double, 3.0)
@measurement_service.configuration("Probe attenuation", nims.DataType.Float, 1.0)
# configure outputs
@measurement_service.output("Source voltage (V)", nims.DataType.Float)
@measurement_service.output("Source current (A)", nims.DataType.Float)
@measurement_service.output("Load voltage (V)", nims.DataType.Float)
@measurement_service.output("Load current (A)", nims.DataType.Float)
@measurement_service.output("Ripple RMS voltage (V)", nims.DataType.Float)
@measurement_service.output("Ripple P-P voltage (V)", nims.DataType.Float)
@measurement_service.output("Ripple graph", nims.DataType.DoubleXYData)
@measurement_service.output("DUT status", nims.DataType.String)
def measure(
        mode_of_operation: enumerate,
        dut_setup_time: float,
        aperture_time: float,
        source_resource_name: str,
        source_voltage_level: float,
        source_current_limit: float,
        load_resource_name: str,
        load_current_level: float,
        load_voltage_limit_range: float,
        scope_resource_name: str,
        scope_channel_name: str,
        scope_sample_rate: float,
        scope_acquisition_time: float,
        scope_probe_attenuation: float,
) -> (float, float, float, float, float, float, DoubleXYData, str):
    # EDIT SOURCE AND LOAD CHANNEL NAMES HERE FOR USING DIFFERENT CHANNELS
    source_device_channel = '0'
    load_device_channel = '0'

    ripple_voltages = []
    supply_voltage = supply_current = load_voltage = load_current = ripple_voltage_rms = ripple_voltage_pk_to_pk = 0
    ripple_graph = DoubleXYData()
    dut_status = ''

    if mode_of_operation == ModeOfOperation.power_on_dut:
        result = power_on_dut(source_resource_name, source_device_channel, source_voltage_level, source_current_limit)
        supply_voltage = result[0]
        supply_current = result[1]
        dut_status = format_dut_info("ON", supply_voltage, supply_current)
        result.clear()

    elif mode_of_operation == ModeOfOperation.perform_measurement:

        dcpower_source_session = open_and_configure_dcpower_source(source_resource_name, source_device_channel,
                                                                   source_voltage_level, source_current_limit,
                                                                   dut_setup_time, aperture_time)
        result = measure_dcpower(dcpower_source_session, source_device_channel)
        supply_voltage = result[0]
        supply_current = result[1]
        dcpower_source_session = result[2]
        result.clear()

        dcpower_load_session = open_and_configure_dcpower_load(load_resource_name, load_device_channel,
                                                               load_current_level, load_voltage_limit_range,
                                                               dut_setup_time, aperture_time)
        result = measure_dcpower(dcpower_load_session, load_device_channel)
        load_voltage = result[0]
        load_current = result[1]
        dcpower_load_session = result[2]

        # code to reset DC sources if error occurs at scope device
        try:
            ripple_generator = perform_scope_acquisition(
                scope_resource_name,
                scope_channel_name,
                scope_sample_rate,
                scope_acquisition_time,
                scope_probe_attenuation,
                ripple_voltages,
                ripple_graph
            )

            for ripples in ripple_generator:
                ripple_graph_array = np.array(ripples, dtype=np.float64)
                ripple_voltage_rms = calculate_rms(ripple_graph_array)
                ripple_voltage_pk_to_pk = calculate_pk_to_pk(ripple_graph_array)
                yield (supply_voltage, supply_current, load_voltage, load_current,
                       ripple_voltage_rms, ripple_voltage_pk_to_pk, ripple_graph, dut_status)
        except Exception as e:
            reset_dc_source(dcpower_source_session, source_device_channel)
            reset_dc_source(dcpower_load_session, load_device_channel)
            raise e

        close_dcpower(dcpower_load_session, load_device_channel)
        close_dcpower(dcpower_source_session, source_device_channel)
        dut_status = ""

    elif mode_of_operation == ModeOfOperation.power_off_dut:
        power_off_dut(source_resource_name, source_device_channel, load_resource_name, load_device_channel)
        dut_status = "The DUT is powered OFF"

    return (supply_voltage, supply_current, load_voltage, load_current,
            ripple_voltage_rms, ripple_voltage_pk_to_pk, ripple_graph, dut_status)


@click.command
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable verbose logging. Repeat to increase verbosity.",
)
def main(verbose: int) -> None:
    """Host the ripple service."""
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
