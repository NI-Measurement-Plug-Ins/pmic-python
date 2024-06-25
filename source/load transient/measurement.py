import sys
from enum import Enum

import ni_measurementlink_service as nims
from _helpers import *

from configure_dcpower import *
import numpy as np
from ni_measurementlink_service._internal.stubs.ni.protobuf.types.xydata_pb2 import DoubleXYData

class ModeOfOperation(Enum):
    power_on_dut = 0
    perform_measurement = 1
    power_off_dut = 2
    pass

def format_dut_info(status, voltage, current):
    return "The DUT is powered %s\nVoltage Level: %.3f V\nCurrent Level: %.3f A" % (status, voltage, current)

script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(
    service_config_path=service_directory / "Load_Transient_PMIC.serviceconfig",
    version="1.0.0.0",
    ui_file_paths=[service_directory / "Load_Transient_PMIC.measui"],
)


@measurement_service.register_measurement
# GUI inputs and default values
@measurement_service.configuration("Mode of operation", nims.DataType.Enum,
                                   default_value=ModeOfOperation.perform_measurement, enum_type=ModeOfOperation)
@measurement_service.configuration("DUT setup time (s)", nims.DataType.Float, 0.05)
@measurement_service.configuration("Level dwell time (s)", nims.DataType.Float, 1.0e-3)
@measurement_service.configuration("Nominal output voltage (V)", nims.DataType.Float, 3.3)
@measurement_service.configuration("Source resource name", nims.DataType.String, 'PPS')
@measurement_service.configuration("Source voltage level (V)", nims.DataType.Float, 12.0)
@measurement_service.configuration("Source current limit (A)", nims.DataType.Float, 25.0)
@measurement_service.configuration("Voltage gain bandwidth (Hz)", nims.DataType.Float, 2000.0)
@measurement_service.configuration("Voltage compensation frequency (Hz)", nims.DataType.Float, 3530.0)
@measurement_service.configuration("Voltage pole-zero ratio", nims.DataType.Float, 2.0)
@measurement_service.configuration("Load resource name", nims.DataType.String, 'E-load')
@measurement_service.configuration("Load voltage limit range (V)", nims.DataType.Float, 6.0)
@measurement_service.configuration("Sample rate (Hz)", nims.DataType.Double, 1.8e6)
@measurement_service.configuration("Load current set point 1 (A)", nims.DataType.Float, 4.0)
@measurement_service.configuration("Load current set point 2 (A)", nims.DataType.Float, 14.0)
@measurement_service.configuration("Current gain bandwidth (Hz)", nims.DataType.Float, 14e3)
@measurement_service.configuration("Current compensation frequency (Hz)", nims.DataType.Float, 180e3)
@measurement_service.configuration("Current pole-zero ratio", nims.DataType.Float, 0.3)
# GUI outputs
@measurement_service.output("Load voltage vs time", nims.DataType.DoubleXYData)
@measurement_service.output("Load current vs time", nims.DataType.DoubleXYData)
@measurement_service.output("DUT status", nims.DataType.String)
# main function that is run when the service is called or "Run" button is clicked in InstrumentStudio
def measure(
        mode_of_operation: enumerate,
        dut_setup_time: float,
        level_dwell_time: float,
        nominal_output_voltage: float, #Unused: Placeholder for DUT Setup
        source_resource_name: str,
        source_voltage_level: float,
        source_current_limit: float,
        voltage_gain_bandwidth: float,
        voltage_compensation_frequency: float,
        voltage_pole_zero_ratio: float,
        load_resource_name: str,
        load_voltage_limit_range: float,
        sample_rate: float,
        load_current_set_point_1: float,
        load_current_set_point_2: float,
        current_gain_bandwidth: float,
        current_compensation_frequency: float,
        current_pole_zero_ratio: float,
) -> (DoubleXYData, DoubleXYData, str):
    # ToDo: edit the source and load channel names here for using different channels
    # the source and load channels are hardcoded to channel 0 as they are single channel devices
    source_device_channel = '0'
    load_device_channel = '0'

    supply_voltage = 0
    supply_current = 0
    dut_status = ''
    load_voltage_graph = DoubleXYData()
    load_current_graph = DoubleXYData()

    if mode_of_operation == ModeOfOperation.power_on_dut:
            result = power_on_dut(source_resource_name, source_device_channel, source_voltage_level, source_current_limit)
            supply_voltage = result[0]
            supply_current = result[1]
            dut_status = format_dut_info("ON", supply_voltage, supply_current)
            result.clear()

    elif mode_of_operation == ModeOfOperation.perform_measurement:
        # Open and configure source SMU
        dcpower_source_session = open_and_configure_dcpower_source(source_resource_name, source_device_channel,
                                                                   source_voltage_level, source_current_limit,
                                                                   dut_setup_time, voltage_gain_bandwidth, 
                                                                   voltage_compensation_frequency,voltage_pole_zero_ratio)
        
        # Open and configure load SMU in sequence mode
        (dcpower_load_session, num_samples_to_fetch, measure_record_delta_time) = \
        open_and_configure_dcpower_load(load_resource_name, load_device_channel, load_current_set_point_1,
                                        load_voltage_limit_range, dut_setup_time,
                                        current_gain_bandwidth, current_compensation_frequency,
                                        current_pole_zero_ratio, sample_rate, level_dwell_time,
                                        load_current_set_point_1, load_current_set_point_2)
        
        # Initiate sequence and fetch measurements 
        measurements = measure_load_transient(dcpower_load_session, load_device_channel, num_samples_to_fetch)

        # Convert measurements to numpy arrays
        voltage_data = np.array([measurement.voltage for measurement in measurements])
        current_data = np.array([measurement.current for measurement in measurements])

        # Create voltage vs time graph for type DoubleXYData
        t = 0
        dt = measure_record_delta_time.total_seconds()
        for v in voltage_data:
                load_voltage_graph.x_data.append(t)
                load_voltage_graph.y_data.append(v)
                t += dt

        # Create current vs time graph for type DoubleXYData
        t = 0
        for c in current_data:
                load_current_graph.x_data.append(t)
                load_current_graph.y_data.append(c)
                t += dt

        dut_status = "The measurement has performed successfully"

    elif mode_of_operation == ModeOfOperation.power_off_dut:
        power_off_dut(source_resource_name, source_device_channel, load_resource_name, load_device_channel)
        dut_status = "The DUT is powered OFF"

    return (load_voltage_graph, load_current_graph, dut_status)


@click.command
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable verbose logging. Repeat to increase verbosity.",
)
def main(verbose: int) -> None:
    """Host the load_transient service."""
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
