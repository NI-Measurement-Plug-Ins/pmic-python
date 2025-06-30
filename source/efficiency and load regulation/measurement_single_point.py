import logging
import pathlib
import sys

import click
import ni_measurementlink_service as nims

from configure_dc_power import *

script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(
    service_config_path=service_directory / "EfficiencyAndLoadRegulation_PMIC.serviceconfig",
    version="1.0.0.0",
    ui_file_paths=[service_directory / "EfficiencyAndLoadRegulation_PMIC.vi"],
)


@measurement_service.register_measurement
# On-Off feature
@measurement_service.configuration('Mode of operation', nims.DataType.Enum, ModeOfOperation.PerformMeasurement, enum_type=ModeOfOperation)
# Measurement Settings
@measurement_service.configuration('DUT setup time', nims.DataType.Double, 1.0)
@measurement_service.configuration('Source delay', nims.DataType.Double, 0.005)
@measurement_service.configuration('Aperture time', nims.DataType.Double, 0.005)
@measurement_service.configuration('Nominal output voltage', nims.DataType.Double, 3.3)
# Source Settings
@measurement_service.configuration('Source resource name', nims.DataType.String, 'PXI1Slot2')
@measurement_service.configuration('Source current limit', nims.DataType.Double, 25.0)
@measurement_service.configuration('Source maximum power', nims.DataType.Double, 300.0)
@measurement_service.configuration('Source voltage', nims.DataType.Double, 12.0)
# Load Settings
@measurement_service.configuration('Load resource name', nims.DataType.String, 'PXI1Slot3')
@measurement_service.configuration('Load voltage limit range', nims.DataType.Double, 5.0)
@measurement_service.configuration('Load current', nims.DataType.Double, 1.0)
# configure outputs
@measurement_service.output('Status', nims.DataType.String)
@measurement_service.output('Measured efficiency', nims.DataType.Double)
@measurement_service.output('Measured load voltage', nims.DataType.Double)
@measurement_service.output('Measured load voltage deviation', nims.DataType.Double)
def measure(
        mode_of_operation: Enum,
        dut_setup_time: float,
        source_delay: float,
        aperture_time: float,
        nominal_output_voltage: float,
        source_resource_name: str,
        source_current_limit: float,
        source_maximum_power: float,
        source_voltage: float,
        load_resource_name: str,
        load_voltage_limit_range: float,
        load_current: float,
):
    source_device_channel: str = '0'
    load_device_channel: str = '0'
    status: str = ""
    measured_efficiency: float = 0.0
    measured_load_voltage: float = 0.0
    measured_load_voltage_deviation: float = 0.0

    if mode_of_operation == ModeOfOperation.Power_On_DUT:
        res = power_on_dut(source_resource_name, source_device_channel, source_voltage, source_current_limit)
        status = format_power_on_result(res[0], res[1])

    elif mode_of_operation == ModeOfOperation.PerformMeasurement:
        source_session = Session(source_resource_name, source_device_channel)
        load_session = Session(load_resource_name, load_device_channel)
        try:
            initiate_source(
                source_session,
                source_device_channel,
                source_voltage,
                source_current_limit,
                source_maximum_power,
                dut_setup_time
            )
            initiate_load(
                load_session,
                load_device_channel,
                load_current,
                load_voltage_limit_range,
                dut_setup_time
            )
            configure_source(
                source_session,
                source_device_channel,
                [source_voltage],
                source_current_limit,
                source_maximum_power,
                1,
                source_delay,
                aperture_time
            )
            configure_load(
                load_session,
                load_device_channel,
                [load_current],
                load_voltage_limit_range,
                aperture_time,
                build_trigger_terminal(source_resource_name, source_device_channel, 'SourceTrigger'),
                build_trigger_terminal(source_resource_name, source_device_channel, 'SourceCompleteEvent')
            )
            load_session.channels[load_device_channel].initiate()
            source_session.channels[source_device_channel].initiate()
            load_session.channels[load_device_channel].wait_for_event(event_id=Event.SEQUENCE_ENGINE_DONE)
            # Perform single measurement
            result = perform_single_measurement(
                source_session,
                source_device_channel,
                load_session,
                load_device_channel,
                source_voltage,
                load_current,
                nominal_output_voltage
            )
            measured_efficiency = result["efficiency"]
            measured_load_voltage = result["load_voltage"]
            measured_load_voltage_deviation = result["load_voltage_deviation"]
            status = 'Measurement successful'
            reset_sessions(source_session, source_device_channel, load_session, load_device_channel)
        except Exception:
            reset_sessions(source_session, source_device_channel, load_session, load_device_channel)
            raise

    elif mode_of_operation == ModeOfOperation.Power_Off_DUT:
        power_off_dut(source_resource_name, source_device_channel, load_resource_name, load_device_channel)
        status = 'The DUT is powered off'

    return (
        status,
        measured_efficiency,
        measured_load_voltage,
        measured_load_voltage_deviation,
    )


@click.command
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable verbose logging. Repeat to increase verbosity.",
)
def main(verbose: int) -> None:
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
