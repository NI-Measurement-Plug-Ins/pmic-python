"""PMIC Output Voltage Accuracy Measurement"""
import sys
from enum import Enum

import ni_measurementlink_service as nims
from ni_measurementlink_service._internal.stubs.ni.protobuf.types.xydata_pb2 import DoubleXYData

from configure_dcpower import *
from _helpers import *


class ModeOfOperation(Enum):
    Power_on_dut = 0
    Perform_measurement = 1
    Power_off_dut = 2


script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(
    service_config_path=service_directory / "OutputVoltageAccuracy_PMIC.serviceconfig",
    version="1.0.0.0",
    ui_file_paths=[service_directory / "OutputVoltageAccuracy_PMIC.measui"],
)


def perform_measurement(measurements, total, nominal_output_voltage):
    output_voltage = total / len(measurements)
    diff = abs(output_voltage - nominal_output_voltage)

    output_voltage_accuracy = (diff / nominal_output_voltage) * 100
    output_voltage_accuracy_mv = diff

    return output_voltage, output_voltage_accuracy_mv, output_voltage_accuracy


@measurement_service.register_measurement
# On-Off feature
@measurement_service.configuration("Mode of operation", nims.DataType.Enum, ModeOfOperation.Perform_measurement,
                                   enum_type=ModeOfOperation)
# Measurement Settings
@measurement_service.configuration("Dut setup time (s)", nims.DataType.Float, 1.0)
@measurement_service.configuration("Aperture time (s)", nims.DataType.Float, 0.005)
# Aperture time is the period during which an ADC reads the voltage or current on a power supply or SMU. 
@measurement_service.configuration("Nominal output voltage (V)", nims.DataType.Float, 3.3)
# Source Settings
@measurement_service.configuration("Source resource name", nims.DataType.String, 'PPS')
@measurement_service.configuration("Source voltage level (V)", nims.DataType.Float, 6.0)
@measurement_service.configuration("Source current limit (A)", nims.DataType.Float, 25.0)
# Load Settings
@measurement_service.configuration("Load resource name", nims.DataType.String, 'E-load')
@measurement_service.configuration("Load current level (A)", nims.DataType.Float, 1.0)
@measurement_service.configuration("Load voltage limit range (V)", nims.DataType.Float, 6.0)
@measurement_service.configuration("Measurement duration (s)", nims.DataType.Float, 1.0)
# configure outputs
@measurement_service.output("Load voltage v/s time", nims.DataType.DoubleXYData)
@measurement_service.output("Measured output voltage(V)", nims.DataType.Float)
@measurement_service.output("Output voltage accuracy (V)", nims.DataType.Float)
@measurement_service.output("Output voltage accuracy (%)", nims.DataType.Float)
@measurement_service.output("DUT status", nims.DataType.String)
def measure(
        mode_of_operation: enumerate,
        dut_setup_time: float,
        aperture_time: float,
        nominal_output_voltage: float,
        source_resource_name: str,
        source_voltage_level: float,
        source_current_limit: float,
        load_resource_name: str,
        load_current_level: float,
        load_voltage_limit_range: float,
        measurement_duration: float
) -> (DoubleXYData, float, float, float, str):
    # EDIT SOURCE AND LOAD CHANNEL NAMES HERE FOR USING DIFFERENT CHANNELS
    source_device_channel = '0'
    load_device_channel = '0'

    # Initialize results
    load_volt_vs_time = DoubleXYData()
    output_voltage = output_voltage_accuracy_mv = output_voltage_accuracy = 0
    dut_status = ""

    if mode_of_operation == ModeOfOperation.Power_on_dut:

        result = power_on_dut(source_resource_name, source_device_channel, source_voltage_level, source_current_limit)
        supply_voltage = result[0]
        supply_current = result[1]
        dut_status = format_dut_info("ON", supply_voltage, supply_current)
        result.clear()

    elif mode_of_operation == ModeOfOperation.Perform_measurement:

        # Configure source
        source_session = open_and_configure_dcpower_source(source_resource_name, source_device_channel,
                                                           source_voltage_level, source_current_limit,
                                                           dut_setup_time, aperture_time)
        source_session.initiate()

        # Configure load
        load_session = open_and_configure_dcpower_load(load_resource_name, load_device_channel,
                                                       load_current_level, load_voltage_limit_range,
                                                       dut_setup_time, aperture_time)

        no_of_samples_to_fetch = int(measurement_duration / aperture_time) + 1
        # Perform measurement
        measurements = measure_voltage(load_session, load_device_channel, no_of_samples_to_fetch)
        length = len(measurements)
        dt = measurement_duration / length
        total = 0
        for i in range(1, length + 1):
            total += measurements[i - 1]
            load_volt_vs_time.x_data.append(float(i * dt))
            load_volt_vs_time.y_data.append(measurements[i - 1])

        output_voltage, output_voltage_accuracy_mv, output_voltage_accuracy = perform_measurement(measurements, total,
                                                                                                  nominal_output_voltage)
        close_dcpower(load_session, load_device_channel)
        close_dcpower(source_session, source_device_channel)
        dut_status = ""

    elif mode_of_operation == ModeOfOperation.Power_off_dut:
        power_off_dut(source_resource_name, source_device_channel, load_resource_name, load_device_channel)
        dut_status = "The DUT is powered OFF"

    return (load_volt_vs_time, output_voltage, output_voltage_accuracy_mv,
            output_voltage_accuracy, dut_status)


@click.command
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable verbose logging. Repeat to increase verbosity.",
)
def main(verbose: int) -> None:
    """Host the output_voltage_accuracy service."""
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
