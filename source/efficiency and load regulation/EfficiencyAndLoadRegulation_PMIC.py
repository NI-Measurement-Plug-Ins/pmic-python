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
@measurement_service.configuration('Mode of operation', nims.DataType.Enum, ModeOfOperation.PerformMeasurement, enum_type=ModeOfOperation)
@measurement_service.configuration('DUT setup time', nims.DataType.Double, 1.0)
@measurement_service.configuration('Source delay', nims.DataType.Double, 0.005)
@measurement_service.configuration('Aperture time', nims.DataType.Double, 0.005)
@measurement_service.configuration('Nominal output voltage', nims.DataType.Double, 3.3)
@measurement_service.configuration('Source resource name', nims.DataType.String, 'PPS')
@measurement_service.configuration('Source current limit', nims.DataType.Double, 25.0)
@measurement_service.configuration('Source maximum power', nims.DataType.Double, 300.0)
@measurement_service.configuration('Source start voltage', nims.DataType.Double, 6.0)
@measurement_service.configuration('Source stop voltage', nims.DataType.Double, 20.0)
@measurement_service.configuration('Source voltage sweep points', nims.DataType.Int32, 4)
@measurement_service.configuration('Load resource name', nims.DataType.String, 'E-load')
@measurement_service.configuration('Load voltage limit range', nims.DataType.Double, 5.0)
@measurement_service.configuration('Load sweep type', nims.DataType.String, 'Linear')
@measurement_service.configuration('Load start current', nims.DataType.Double, 0.1)
@measurement_service.configuration('Load stop current', nims.DataType.Double, 24.0)
@measurement_service.configuration('Load current sweep points/points per decade', nims.DataType.Int32, 10)
@measurement_service.output('Status', nims.DataType.String)
@measurement_service.output('Voltage values', nims.DataType.DoubleArray1D)
@measurement_service.output('Source sweep points', nims.DataType.Int32)
@measurement_service.output('Load sweep points', nims.DataType.Int32)
@measurement_service.output('Load currents', nims.DataType.DoubleArray1D)
@measurement_service.output('Efficiency', nims.DataType.DoubleArray1D)
@measurement_service.output('Load voltages', nims.DataType.DoubleArray1D)
@measurement_service.output('Load voltage deviation', nims.DataType.DoubleArray1D)
def measure(
        mode_of_operation: Enum,
        dut_setup_time: float,
        source_delay: float,
        aperture_time: float,
        nominal_output_voltage: float,
        source_resource_name: str,
        source_current_limit: float,
        source_maximum_power: float,
        source_start_voltage: float,
        source_stop_voltage: float,
        source_voltage_sweep_points: int,
        load_resource_name: str,
        load_voltage_limit_range: float,
        load_sweep_type: str,
        load_start_current: float,
        load_stop_current: float,
        load_current_sweep_points_points_per_decade: int,
):
    # Constants
    source_device_channel: str = '0'
    load_device_channel: str = '0'
    load_sweep_type_enum = SweepType.Linear
    # Outputs
    status: str = str()
    voltage_values: list[float] = list()
    source_sweep_points: int = int()
    load_sweep_points: int = int()
    load_currents: list[float] = list()
    efficiency: list[float] = list()
    load_voltages: list[float] = list()
    load_voltage_deviation: list[float] = list()
    # Measure logic start
    if mode_of_operation == ModeOfOperation.Power_On_DUT:
        res = power_on_dut(source_resource_name, source_device_channel, source_start_voltage, source_current_limit)
        status = format_power_on_result(res[0], res[1])
        pass

    elif mode_of_operation == ModeOfOperation.PerformMeasurement:

        if load_sweep_type.lower() == 'logarithmic':
            load_sweep_type_enum = SweepType.Logarithmic
        elif load_sweep_type.lower() != 'linear':
            raise ValueError(f'{load_sweep_type} Sweep Type is not supported ')

        source_session = Session(source_resource_name, source_device_channel)
        load_session = Session(load_resource_name, load_device_channel)
        try:
            voltage_values = generate_sequence(
                SweepType.Linear,
                source_start_voltage,
                source_stop_voltage,
                source_voltage_sweep_points
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
                load_start_current,
                load_voltage_limit_range,
                dut_setup_time
            )
            current_results = generate_sequence(
                load_sweep_type_enum,
                load_start_current,
                load_stop_current,
                load_current_sweep_points_points_per_decade
            )

            load_sweep_points = len(current_results)
            current_values = len(voltage_values) * current_results

            configure_source(
                source_session,
                source_device_channel,
                voltage_values,
                source_current_limit,
                source_maximum_power,
                load_sweep_points,
                source_delay,
                aperture_time
            )
            configure_load(
                load_session,
                load_device_channel,
                current_values,
                load_voltage_limit_range,
                aperture_time,
                build_trigger_terminal(source_resource_name, source_device_channel, 'SourceTrigger'),
                build_trigger_terminal(source_resource_name, source_device_channel, 'SourceCompleteEvent')
            )

            load_session.channels[load_device_channel].initiate()
            source_session.channels[source_device_channel].initiate()

            load_session.channels[load_device_channel].wait_for_event(event_id=Event.SEQUENCE_ENGINE_DONE)
            source_sweep_points = len(voltage_values)

            gen = perform_measurements(
                source_session,
                source_device_channel,
                load_session,
                load_device_channel,
                voltage_values,
                load_sweep_points,
                nominal_output_voltage,
                load_currents,
                load_voltages,
                efficiency,
                load_voltage_deviation
            )
            for _ in gen:
                yield (
                    status,
                    voltage_values,
                    source_sweep_points,
                    load_sweep_points,
                    load_currents,
                    efficiency,
                    load_voltages,
                    load_voltage_deviation,
                )
                pass

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
        voltage_values,
        source_sweep_points,
        load_sweep_points,
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
