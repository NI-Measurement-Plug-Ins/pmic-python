import logging
import pathlib
import sys

import click
import ni_measurementlink_service as nims

# from configure_dc_power import *
from nidcpower_channel_ganging import *

script_or_exe = sys.executable if getattr(sys, "frozen", False) else __file__
service_directory = pathlib.Path(script_or_exe).resolve().parent
measurement_service = nims.MeasurementService(
    service_config_path=service_directory / "Ganged_EfficiencyAndLoadRegulation_PMIC.serviceconfig",
    version="1.0.0.0",
    ui_file_paths=[service_directory / "Measurement UI.vi"],
)


def _safe_cleanup_action(action_name: str, action, session_label: str) -> None:
    """Run one cleanup action and keep going if it fails."""
    try:
        action()
    except Exception as exc:
        logging.warning("Cleanup step '%s' failed for %s session: %s", action_name, session_label, exc)


def _cleanup_ganged_session(ganged_session, session_label: str) -> None:
    """Best-effort shutdown for a ganged session."""
    if ganged_session is None:
        return

    _safe_cleanup_action("abort", lambda: abort(ganged_session), session_label)
    _safe_cleanup_action("output_enabled(False)", lambda: output_enabled(ganged_session, output_enabled=False), session_label)
    _safe_cleanup_action("output_connected(False)", lambda: output_connected(ganged_session, output_connected=False), session_label)
    _safe_cleanup_action("reset", lambda: reset(ganged_session), session_label)
    _safe_cleanup_action("close", lambda: close(ganged_session), session_label)


@measurement_service.register_measurement
# On-Off feature
#TODO Remove mode of operation as it will not be needed
# @measurement_service.configuration('Mode of operation', nims.DataType.Enum, ModeOfOperation.PerformMeasurement, enum_type=ModeOfOperation)
# Measurement Settings
@measurement_service.configuration('DUT setup time', nims.DataType.Double, 1.0)
@measurement_service.configuration('Source delay', nims.DataType.Double, 0.005)
# Aperture time is the period during which an ADC reads the voltage or current on a power supply or SMU
@measurement_service.configuration('Aperture time', nims.DataType.Double, 0.005)
@measurement_service.configuration('Nominal output voltage', nims.DataType.Double, 3.3)
@measurement_service.configuration('Measurement timeout', nims.DataType.Double, 10.0)
# Source Settings
@measurement_service.configuration('Source master resource name', nims.DataType.String, 'PS_0')
@measurement_service.configuration('Source slave resource names', nims.DataType.StringArray1D, ['PS_1'])
@measurement_service.configuration('Source system configuration', nims.DataType.Enum, GangedConfig.PARALLEL, enum_type=GangedConfig)
@measurement_service.configuration('Source start voltage', nims.DataType.Double, 6.0)
@measurement_service.configuration('Source stop voltage', nims.DataType.Double, 14.0)
@measurement_service.configuration('Source voltage sweep points', nims.DataType.Int32, 4)
@measurement_service.configuration('Source voltage level range', nims.DataType.Double, 20.0)
@measurement_service.configuration('Source sense', nims.DataType.Int32, MeasurementSense.REMOTE.value)
@measurement_service.configuration('Source limit symmetry', nims.DataType.Enum, ComplianceLimitSymmetry.ASYMMETRIC, enum_type=ComplianceLimitSymmetry)
@measurement_service.configuration('Source current limit range', nims.DataType.Double, 25.0)
@measurement_service.configuration('Source current limit low', nims.DataType.Double, -0.6)
@measurement_service.configuration('Source current limit high', nims.DataType.Double, 25.0)
@measurement_service.configuration('Source transient response', nims.DataType.Int32, InstrumentTransientResponse.NORMAL.value)
@measurement_service.configuration('Source voltage gain bandwidth', nims.DataType.Double, 2000.0)
@measurement_service.configuration('Source voltage compensation frequency', nims.DataType.Double, 3530.0)
@measurement_service.configuration('Source voltage pole-zero ratio', nims.DataType.Double, 2.0)
# Load Settings
@measurement_service.configuration('Load master resource name', nims.DataType.String, 'Load_0')
@measurement_service.configuration('Load slave resource names', nims.DataType.StringArray1D, ['Load_1'])
@measurement_service.configuration('Load system configuration', nims.DataType.Enum, GangedConfig.PARALLEL, enum_type=GangedConfig)
@measurement_service.configuration('Load start current', nims.DataType.Double, 1.0)
@measurement_service.configuration('Load stop current', nims.DataType.Double, 50.0)
@measurement_service.configuration('Load current sweep points/points per decade', nims.DataType.Int32, 10)
@measurement_service.configuration('Load sweep type', nims.DataType.String, 'Logarithmic')
@measurement_service.configuration('Load current level range', nims.DataType.Double, 80.0)
@measurement_service.configuration('Load sense', nims.DataType.Int32, MeasurementSense.REMOTE.value)
@measurement_service.configuration('Load limit symmetry', nims.DataType.Enum, ComplianceLimitSymmetry.SYMMETRIC, enum_type=ComplianceLimitSymmetry)
@measurement_service.configuration('Load voltage limit range', nims.DataType.Double, 6.0)
@measurement_service.configuration('Load voltage limit low', nims.DataType.Double, 0.0)
#TODO Check if limit/limit high data type needs to be string instead of Double
@measurement_service.configuration('Load voltage limit high', nims.DataType.Double, float("Inf"))
@measurement_service.configuration('Load transient response', nims.DataType.Int32, InstrumentTransientResponse.NORMAL.value)
@measurement_service.configuration('Load current gain bandwidth', nims.DataType.Double, 14000.0)
@measurement_service.configuration('Load current compensation frequency', nims.DataType.Double, 180000.0)
@measurement_service.configuration('Load current pole-zero ratio', nims.DataType.Double, 0.3)
# Configure outputs
#TODO validate if more outputs are needed
# @measurement_service.output('Status', nims.DataType.String)
@measurement_service.output('Voltage values', nims.DataType.DoubleArray1D)
@measurement_service.output('Source sweep points', nims.DataType.Int32)
@measurement_service.output('Load sweep points', nims.DataType.Int32)
@measurement_service.output('Efficiency', nims.DataType.DoubleArray1D)
@measurement_service.output('Ganged load currents', nims.DataType.DoubleArray1D)
@measurement_service.output('Ganged load voltages', nims.DataType.DoubleArray1D)
@measurement_service.output('Load voltage deviation', nims.DataType.DoubleArray1D)
def measure(
        dut_setup_time: float,
        source_delay: float,
        aperture_time: float,
        nominal_output_voltage: float,
        timeout: float,
        master_source_resource_name: str,
        slave_source_resource_names: list[str],
        source_system_config: Enum, #GangedConfig
        source_start_voltage: float,
        source_stop_voltage: float,
        source_voltage_sweep_points: int,
        source_voltage_level_range: float,
        source_sense: Enum, #Sense
        source_limit_symmetry: Enum, #LimitSymmetry
        source_current_limit_range: float,
        source_current_limit_low: float,
        source_current_limit_high: float,
        source_transient_response: Enum, #TransientResponse
        source_voltage_gain_bandwidth: float,
        source_voltage_compensation_frequency: float,
        source_voltage_pole_zero_ratio: float,
        master_load_resource_name: str,
        slave_load_resource_names: list[str],
        load_system_config: Enum, #GangedConfig
        load_start_current: float,
        load_stop_current: float,
        load_current_sweep_points_points_per_decade: int,
        load_sweep_type: str,
        load_current_level_range: float,
        load_sense: Enum, #Sense
        load_limit_symmetry: Enum, #LimitSymmetry
        load_voltage_limit_range: float,
        load_voltage_limit_low: float,
        load_voltage_limit_high: float, #also check if this should be float or string
        load_transient_response: Enum, #TransientResponse
        load_current_gain_bandwidth: float,
        load_current_compensation_frequency: float,
        load_current_pole_zero_ratio: float,
):
    # Constants
    load_sweep_type_enum = SweepType.Linear
    source_ganged_session = None
    load_ganged_session = None
    # Outputs
    voltage_values: list[float] = []
    source_sweep_points = 0
    load_sweep_points = 0
    load_currents: list[float] = []
    efficiency: list[float] = []
    load_voltages: list[float] = []
    load_voltage_deviation: list[float] = []
    # Measure logic start

    try:
        if load_sweep_type.lower() == 'logarithmic':
            load_sweep_type_enum = SweepType.Logarithmic
        elif load_sweep_type.lower() != 'linear':
            raise ValueError(f'{load_sweep_type} Sweep Type is not supported ')

        ## Initialize source configuration
        source_channel_list = channel_list(master_source_resource_name, slave_source_resource_names)
        source_ganged_session = initialize(source_channel_list, ganged_config=source_system_config)
        configure_source_mode(source_ganged_session, source_mode=SourceMode.SINGLE_POINT)
        configure_sense(source_ganged_session, sense=Sense(source_sense))
        configure_output_function(source_ganged_session, output_function=OutputFunction.DC_VOLTAGE)
        configure_voltage_level_range(source_ganged_session, source_voltage_level_range)
        configure_current_limit_range(source_ganged_session, source_current_limit_range)
        configure_current_limit(source_ganged_session, source_current_limit_high, source_current_limit_low, source_limit_symmetry)
        source_sweep_values = generate_sequence(SweepType.Linear, source_start_voltage, source_stop_voltage, source_voltage_sweep_points)
        configure_voltage_level(source_ganged_session, source_sweep_values[0])
        configure_transient_response(source_ganged_session, TransientResponse(source_transient_response), OutputFunction.DC_VOLTAGE, source_voltage_gain_bandwidth, source_voltage_compensation_frequency, source_voltage_pole_zero_ratio)
        configure_source_delay(source_ganged_session, source_delay=dut_setup_time)
        output_enabled(source_ganged_session, output_enabled=True)
        configure_triggers(source_ganged_session)
        commit(source_ganged_session)
        initiate(source_ganged_session)
        wait_for_event(source_ganged_session, timeout=timeout)
        abort(source_ganged_session)

        ## Initialize load configuration
        load_channel_list = channel_list(master_load_resource_name, slave_load_resource_names)
        load_ganged_session = initialize(load_channel_list, ganged_config=load_system_config)
        configure_source_mode(load_ganged_session, source_mode=SourceMode.SINGLE_POINT)
        configure_sense(load_ganged_session, sense=Sense(load_sense))
        configure_output_function(load_ganged_session, output_function=OutputFunction.DC_CURRENT)
        configure_voltage_limit(load_ganged_session, load_voltage_limit_high, load_voltage_limit_low, load_limit_symmetry)
        configure_voltage_limit_range(load_ganged_session, load_voltage_limit_range)
        configure_current_level_range(load_ganged_session, load_current_level_range)
        configure_current_level(load_ganged_session, load_stop_current)
        configure_transient_response(load_ganged_session, TransientResponse(load_transient_response), OutputFunction.DC_CURRENT, load_current_gain_bandwidth, load_current_compensation_frequency, load_current_pole_zero_ratio)
        configure_source_delay(load_ganged_session, source_delay=dut_setup_time)
        output_enabled(load_ganged_session, output_enabled=True)
        configure_triggers(load_ganged_session)
        commit(load_ganged_session)
        initiate(load_ganged_session)
        wait_for_event(load_ganged_session, timeout=timeout)
        abort(load_ganged_session)

        ## Configure source to sequence
        configure_source_mode(source_ganged_session, source_mode=SourceMode.SEQUENCE)
        configure_output_function(source_ganged_session, output_function=OutputFunction.DC_VOLTAGE)
        configure_transient_response(source_ganged_session, TransientResponse(source_transient_response), OutputFunction.DC_VOLTAGE, source_voltage_gain_bandwidth, source_voltage_compensation_frequency, source_voltage_pole_zero_ratio)
        configure_source_delay(source_ganged_session, source_delay=source_delay)
        configure_aperture_time(source_ganged_session, aperture_time=aperture_time)

        ## Configure load to sequence
        configure_source_mode(load_ganged_session, source_mode=SourceMode.SEQUENCE)
        configure_output_function(load_ganged_session, output_function=OutputFunction.DC_CURRENT)
        configure_transient_response(load_ganged_session, TransientResponse(load_transient_response), OutputFunction.DC_CURRENT, load_current_gain_bandwidth, load_current_compensation_frequency, load_current_pole_zero_ratio)
        configure_source_delay(load_ganged_session, source_delay=source_delay)
        configure_aperture_time(load_ganged_session, aperture_time=aperture_time)
        load_sweep_values = generate_sequence(load_sweep_type_enum, load_start_current, load_stop_current, load_current_sweep_points_points_per_decade)

        source_sweep_points = len(source_sweep_values)
        load_sequence = []
        for _ in range(source_sweep_points):
            for current in load_sweep_values:
                load_sequence.append(current)

        set_sequence(load_ganged_session, values=load_sequence, source_delays=source_delay, output_function=OutputFunction.DC_CURRENT)

        load_sweep_points = len(load_sweep_values)
        source_sequence = []
        for voltage in source_sweep_values:
            for _ in range(load_sweep_points):
                source_sequence.append(voltage)

        set_sequence(source_ganged_session, values=source_sequence, source_delays=source_delay, output_function=OutputFunction.DC_VOLTAGE)

        ## Configure triggers
        source_trigger_terminal = build_trigger_terminal(source_ganged_session.session_list[0], "0", "SourceTrigger")
        source_complete_terminal = build_trigger_terminal(source_ganged_session.session_list[0], "0", "SourceCompleteEvent")
        configure_digital_edge_source_trigger(load_ganged_session, source_trigger_terminal)
        configure_digital_edge_measure_trigger(load_ganged_session, source_complete_terminal)
        configure_triggers(load_ganged_session, measure_when=MeasureWhen.ON_MEASURE_TRIGGER)

        ## Initiate devices
        initiate(load_ganged_session)
        initiate(source_ganged_session)

        wait_for_event(load_ganged_session, event=Event.SEQUENCE_ENGINE_DONE, timeout=timeout)

        ## Perform measurement
        load_sweep_points = len(load_sweep_values)
        source_sweep_points = len(source_sweep_values)
        for voltage in source_sweep_values:
            voltage_values.append(voltage)
            for _ in range(load_sweep_points):
                # Efficiency calculation
                ganged_source_v, ganged_source_i = measure_multiple(source_ganged_session)[:2]
                ganged_load_v, ganged_load_i = measure_multiple(load_ganged_session)[:2]
                ganged_source_p = abs(ganged_source_v * ganged_source_i)
                ganged_load_p = abs(ganged_load_v * ganged_load_i)
                eff = (ganged_load_p / ganged_source_p) * 100
                efficiency.append(eff)

                # Load measurements
                load_currents.append(abs(ganged_load_i))
                load_voltages.append(ganged_load_v)

                # Load voltage deviation
                load_voltage_deviation.append(((load_voltages[-1] - nominal_output_voltage) / nominal_output_voltage) * 100)
    except Exception:
        logging.exception("Measurement execution failed")
        raise
    finally:
        _cleanup_ganged_session(load_ganged_session, "load")
        _cleanup_ganged_session(source_ganged_session, "source")


    # Measure logic end
    return (
        # status,
        voltage_values,
        source_sweep_points,
        load_sweep_points,
        efficiency,
        load_currents,
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
