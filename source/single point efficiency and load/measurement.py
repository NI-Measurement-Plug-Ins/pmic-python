import logging
import pathlib
import sys

import click
import ni_measurement_plugin_sdk_service as nims

from configure_dc_power import *

script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(  # Check if class name is still MeasurementService
    service_config_path=service_directory / "EfficiencyAndLoadRegulation_PMIC.serviceconfig",
    version="1.0.0.0",
    ui_file_paths=[service_directory / "BuiltUI/PMIC UI.lvlibp/Measurement UI.vi"], # Add UI file paths if any
)


@measurement_service.register_measurement
# On-Off feature
@measurement_service.configuration('Mode of operation', nims.DataType.Enum, ModeOfOperation.PerformMeasurement, enum_type=ModeOfOperation)
# Measurement Settings
@measurement_service.configuration('DUT setup time', nims.DataType.Double, 1.0)
@measurement_service.configuration('Source delay', nims.DataType.Double, 0.005)
# Aperture time is the period during which an ADC reads the voltage or current on a power supply or SMU
@measurement_service.configuration('Aperture time', nims.DataType.Double, 0.005)
@measurement_service.configuration('Nominal output voltage', nims.DataType.Double, 1.3)
# Source Settings
@measurement_service.configuration('Source resource name', nims.DataType.String, 'PPS')
@measurement_service.configuration('Source current limit', nims.DataType.Double, 1.0)
@measurement_service.configuration('Source maximum power', nims.DataType.Double, 50.0)
# Load Settings
@measurement_service.configuration('Load resource name', nims.DataType.String, 'E-load')
@measurement_service.configuration('Load voltage limit range', nims.DataType.Double, 5.0)
@measurement_service.configuration('Source Voltage', nims.DataType.Double, 0)
@measurement_service.configuration('Load Current', nims.DataType.Double, 0)
# configure outputs
@measurement_service.output('Status', nims.DataType.String)
@measurement_service.output('Load currents', nims.DataType.Double)
@measurement_service.output('Efficiency', nims.DataType.Double)
@measurement_service.output('Load voltages', nims.DataType.Double)
@measurement_service.output('Load voltage deviation', nims.DataType.Double)
def measure(
        mode_of_operation: Enum,
        dut_setup_time: float,
        source_delay: float,
        aperture_time: float,
        nominal_output_voltage: float,
        source_resource_name: str,
        source_current_limit: float,
        source_maximum_power: float,
        load_resource_name: str,
        load_voltage_limit_range: float,
        source_voltage: float,
        load_current: float,
        
):
    
    # Constants
    source_device_channel: str = '0'
    load_device_channel: str = '0'
    # Outputs
    status: str = str()
    load_currents: float = float()
    efficiency: float = float()
    load_voltages: float = float()
    load_voltage_deviation: float = float()
    # Measure logic start
    if mode_of_operation == ModeOfOperation.Power_On_DUT:
        res = power_on_dut(source_resource_name, source_device_channel, source_voltage, source_current_limit)
        status = format_power_on_result(res[0], res[1])
        pass

    elif mode_of_operation == ModeOfOperation.PerformMeasurement:
        source_session = Session(source_resource_name, source_device_channel)
        load_session = Session(load_resource_name, load_device_channel)
        try:
            initiate_source(
                session=source_session,
                channel_name=source_device_channel,
                voltage_level=source_voltage,
                current_limit=source_current_limit,
                power_limit=source_maximum_power,
                source_delay=dut_setup_time,
            )
            initiate_load(
                session=load_session,
                channel_name=load_device_channel,
                current_level=load_current,
                voltage_limit_range=load_voltage_limit_range,
                source_delay=dut_setup_time
            )

            configure_source(
                session=source_session,
                channel_name=source_device_channel,
                voltage_level=source_voltage,
                current_limit=source_current_limit,
                power_limit=source_maximum_power,
                source_delay=source_delay,
                aperture_time=aperture_time
            )
            configure_load(
                session=load_session,
                channel_name=load_device_channel,
                current_levels=[load_current],
                voltage_limit_range=load_voltage_limit_range,
                aperture_time=aperture_time,
                source_terminal_name=build_trigger_terminal(source_resource_name, source_device_channel, 'SourceTrigger'),
                measure_terminal_name=build_trigger_terminal(source_resource_name, source_device_channel, 'SourceCompleteEvent'),
            )

            load_session.channels[load_device_channel].initiate()
            source_session.channels[source_device_channel].initiate()

            load_session.channels[load_device_channel].wait_for_event(event_id=Event.MEASURE_COMPLETE)

            load_currents, load_voltages, efficiency, load_voltage_deviation = perform_measurements(
                source_session=source_session,
                source_device_channel=source_device_channel,
                load_session=load_session,
                load_device_channel=load_device_channel,
                nominal_output_voltage=nominal_output_voltage,
                load_current=load_current,
                load_voltage=source_voltage,
                efficiency=efficiency,
                load_voltage_deviation=load_voltage_deviation
            )

            reset_sessions(source_session, source_device_channel, load_session, load_device_channel)
            status = 'The measurement is performed successfully'

        except Exception:
            reset_sessions(source_session, source_device_channel, load_session, load_device_channel)
            raise
        pass

    elif mode_of_operation == ModeOfOperation.Power_Off_DUT:
        power_off_dut(source_resource_name, source_device_channel, load_resource_name, load_device_channel)
        status = 'The DUT is powered off'
        pass
    # Measure logic end
    return (
        status,
        load_currents,
        efficiency,
        load_voltages,
        load_voltage_deviation,
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
