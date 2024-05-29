import logging
import pathlib
import sys

import click
import ni_measurementlink_service as nims

from configure_dc_power import *

script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(
    service_config_path=service_directory / "LineRegulation_PMIC.serviceconfig",
    version="1.0.0.0",
    ui_file_paths=[service_directory / "LineRegulation_PMIC.measui"],
)


@measurement_service.register_measurement
@measurement_service.configuration('Mode of operation', nims.DataType.Enum, ModeOfOperation.PerformMeasurement, enum_type=ModeOfOperation)
@measurement_service.configuration('DUT setup time (s)', nims.DataType.Double, 1.0)
@measurement_service.configuration('Source delay (s)', nims.DataType.Double, 0.005)
@measurement_service.configuration('Aperture time (s)', nims.DataType.Double, 0.005)
@measurement_service.configuration('Nominal output voltage (V)', nims.DataType.Double, 3.3)
@measurement_service.configuration('Source resource name', nims.DataType.String, 'PPS')
@measurement_service.configuration('Source current limit (A)', nims.DataType.Double, 25.0)
@measurement_service.configuration('Sweep type', nims.DataType.Enum, SweepType.Linear, enum_type=SweepType)
@measurement_service.configuration('Source maximum power (W)', nims.DataType.Double, 300.0)
@measurement_service.configuration('Source start voltage (V)', nims.DataType.Double, 6.0)
@measurement_service.configuration('Source stop voltage (V)', nims.DataType.Double, 20.0)
@measurement_service.configuration('Pts/Pts per decade', nims.DataType.Int32, 10)
@measurement_service.configuration('Load resource name', nims.DataType.String, 'E-load')
@measurement_service.configuration('Load current level (A)', nims.DataType.Double, 1.0)
@measurement_service.configuration('Load voltage limit range (V)', nims.DataType.Double, 5.0)
@measurement_service.output('Load voltage vs source voltage', nims.DataType.DoubleXYData)
@measurement_service.output('Load voltage dev vs source voltage', nims.DataType.DoubleXYData)
@measurement_service.output('Load voltage (V)', nims.DataType.Double)
@measurement_service.output('Load voltage deviation', nims.DataType.Double)
@measurement_service.output('DUT status', nims.DataType.String)
def measure(
        mode_of_operation: Enum,
        dut_setup_time: float,
        source_delay: float,
        aperture_time: float,
        nominal_output_voltage: float,
        source_resource_name: str,
        source_current_limit: float,
        sweep_type: Enum,
        source_maximum_power: float,
        source_start_voltage: float,
        source_stop_voltage: float,
        pts_pts_per_decade: int,
        load_resource_name: str,
        load_current_level: float,
        load_voltage_limit_range: float,
):
    # Constants
    source_device_channel: str = '0'
    load_device_channel: str = '0'
    # Outputs
    load_voltage_vs_source_voltage: DoubleXYData = DoubleXYData()
    load_voltage_dev_vs_source_voltage: DoubleXYData = DoubleXYData()
    load_voltage: float = float()
    load_voltage_deviation: float = float()
    dut_status: str = ''
    # Measure logic start
    if mode_of_operation == ModeOfOperation.Power_On_DUT:
        res = power_on_dut(source_resource_name, source_device_channel, source_start_voltage, source_current_limit)
        dut_status = format_power_on_result(res[0], res[1])
        pass

    elif mode_of_operation == ModeOfOperation.PerformMeasurement:
        source_session = Session(source_resource_name, source_device_channel)
        load_session = Session(load_resource_name, load_device_channel)
        try:
            voltage_values = generate_sequence(
                sweep_type,
                source_start_voltage,
                source_stop_voltage,
                pts_pts_per_decade
            )

            initiate_source(
                source_session,
                source_device_channel,
                source_start_voltage,
                source_current_limit,
                source_maximum_power,
                dut_setup_time
            )
            initiate_load(
                load_session,
                load_device_channel,
                load_current_level,
                load_voltage_limit_range,
                dut_setup_time
            )
            configure_source(
                source_session,
                source_device_channel,
                voltage_values,
                source_current_limit,
                source_maximum_power,
                source_delay,
                aperture_time
            )
            configure_load(
                load_session,
                load_device_channel,
                load_current_level,
                load_voltage_limit_range,
                aperture_time,
                build_terminal_name(source_session, source_session.get_channel_name(1), 'SourceTrigger'),
                build_terminal_name(source_session, source_session.get_channel_name(1), 'SourceCompleteEvent')
            )

            load_session.channels[load_device_channel].initiate()
            source_session.channels[source_device_channel].initiate()
            source_session.channels[source_device_channel].wait_for_event(event_id=Event.SEQUENCE_ITERATION_COMPLETE)

            gen = perform_measurements(
                source_session,
                source_device_channel,
                load_session,
                load_device_channel,
                voltage_values,
                nominal_output_voltage,
                load_voltage_vs_source_voltage,
                load_voltage_dev_vs_source_voltage
            )

            for _ in gen:
                load_voltage = sum(load_voltage_vs_source_voltage.y_data) / len(load_voltage_vs_source_voltage.y_data)
                load_voltage_deviation = sum(load_voltage_dev_vs_source_voltage.y_data) / len(load_voltage_dev_vs_source_voltage.y_data)
                yield (
                    load_voltage_vs_source_voltage,
                    load_voltage_dev_vs_source_voltage,
                    load_voltage,
                    load_voltage_deviation,
                    dut_status,
                )

            reset_sessions(source_session, source_device_channel, load_session, load_device_channel)
            dut_status = 'The measurement is performed successfully'
        except Exception:
            reset_sessions(source_session, source_device_channel, load_session, load_device_channel)
            raise
        pass

    elif mode_of_operation == ModeOfOperation.Power_Off_DUT:
        power_off_dut(source_resource_name, source_device_channel, load_resource_name, load_device_channel)
        dut_status = 'The DUT is powered off'
        pass
    # Measure logic end
    return (
        load_voltage_vs_source_voltage,
        load_voltage_dev_vs_source_voltage,
        load_voltage,
        load_voltage_deviation,
        dut_status,
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
