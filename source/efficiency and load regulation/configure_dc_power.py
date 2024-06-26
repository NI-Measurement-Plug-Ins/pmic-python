from enum import Enum

from nidcpower import (
    Session, Sense, SourceMode, OutputFunction, Error, Event, MeasureWhen, MeasurementTypes, TriggerType
)


# Mode of operation ENUM
class ModeOfOperation(Enum):
    Power_On_DUT = 0
    PerformMeasurement = 1
    Power_Off_DUT = 2
    pass


# Sweep type indicator ENUM
class SweepType(Enum):
    Linear = 0
    Logarithmic = 1

    def __eq__(self, other):
        return self.value == other.value

    pass


# function to take voltage and current levels and return status string
def format_power_on_result(voltage_level: float, current_level: float) -> str:
    voltage_string = str(voltage_level)
    current_string = str(current_level)
    return (f"The DUT is powered ON\n"
            f"Voltage Level: {voltage_string[:min(len(voltage_string), voltage_string.index('.')+4)]}\n"
            f"Current Level: {current_string[:min(len(current_string), voltage_string.index('.')+4)]}")


# function to generate series of values from start to stop in number of steps specified and SweepType
def generate_sequence(
        sweep_type: Enum,
        start: float, stop: float,
        steps: int,
        with_end_points: bool = True
) -> list[float]:
    res = []
    if start >= stop or steps <= 0:
        return res

    if sweep_type == SweepType.Linear:
        if with_end_points:
            d = (stop - start) / (steps - 1)
            for i in range(steps):
                res.append((start + (i * d)))
            return res
        else:
            d = (stop - start) / (steps + 1)
            for i in range(steps + 2):
                res.append((start + (i * d)))
            return res
    else:
        if with_end_points:
            r = 10 ** (1 / (steps - 1))
            while True:
                res.append(start * (r ** len(res)))
                if res[-1] >= stop:
                    res[-1] = stop
                    return res
        else:
            r = 10 ** (1 / (steps + 1))
            while True:
                res.append(start * (r ** len(res)))
                if res[-1] >= stop:
                    res[-1] = stop
                    return res
    pass


# function to determine current limit based on power boundary
def get_current_limit(voltage_level: float, current_limit: float, power_limit: float) -> float:
    if voltage_level * current_limit > power_limit:
        value = str(float(power_limit / voltage_level))
        return float(value[:min(len(value), value.index('.')+4)])
    return current_limit


# function to build terminal name
def build_trigger_terminal(resource_name: str, channel_name: str, event_name: str) -> str:
    return f'/{resource_name}/Engine{channel_name}/{event_name}'


# function to start source device and keep it in running state
def power_on_dut(
        resource_name: str,
        channel_name: str,
        voltage_level: float,
        current_limit: float
) -> tuple[float, float]:
    session = Session(resource_name=resource_name, channels=channel_name)
    try:
        # configure the session
        session.channels[channel_name].sense = Sense.REMOTE
        session.channels[channel_name].source_mode = SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = OutputFunction.DC_VOLTAGE

        session.channels[channel_name].voltage_level_autorange = True
        session.channels[channel_name].current_limit_autorange = True

        session.channels[channel_name].current_limit = current_limit
        session.channels[channel_name].voltage_level = voltage_level

        session.channels[channel_name].commit()
        session.channels[channel_name].measure_when = MeasureWhen.ON_DEMAND
        session.channels[channel_name].initiate()

        session.channels[channel_name].wait_for_event(event_id=Event.SOURCE_COMPLETE, timeout=5)
        voltage = session.channels[channel_name].measure(measurement_type=MeasurementTypes.VOLTAGE)
        current = session.channels[channel_name].measure(measurement_type=MeasurementTypes.CURRENT)

        session.channels[channel_name].abort()
        session.close()

        return voltage, current

    except Error:
        session.channels[channel_name].abort()
        session.output_enabled = False
        session.channels[channel_name].reset()
        session.close()
        raise

    pass


# function to stop both source and load devices power
def power_off_dut(
        source_resource_name: str,
        source_device_channel: str,
        load_resource_name: str,
        load_device_channel: str
) -> None:
    source_session = Session(resource_name=source_resource_name, channels=source_device_channel)
    load_session = Session(resource_name=load_resource_name, channels=load_device_channel)

    source_session.channels[source_device_channel].output_enabled = False
    load_session.channels[load_device_channel].output_enabled = False

    source_session.channels[source_device_channel].reset()
    load_session.channels[load_device_channel].reset()

    source_session.close()
    load_session.close()
    return


# function to power off power supplies in case of error in perform measurement
def reset_sessions(
        source_session: Session,
        source_device_channel: str,
        load_session: Session,
        load_device_channel: str
) -> None:
    source_session.channels[source_device_channel].abort()
    load_session.channels[load_device_channel].abort()

    source_session.channels[source_device_channel].output_enabled = False
    load_session.channels[load_device_channel].output_enabled = False

    source_session.channels[source_device_channel].reset()
    load_session.channels[load_device_channel].reset()

    source_session.close()
    load_session.close()


# function to start source device and keep power sourcing on
def initiate_source(
        session: Session,
        channel_name: str,
        voltage_level: float,
        current_limit: float,
        power_limit: float,
        source_delay: float
) -> None:
    # configure the source session
    session.channels[channel_name].sense = Sense.REMOTE
    session.channels[channel_name].source_mode = SourceMode.SINGLE_POINT
    session.channels[channel_name].output_function = OutputFunction.DC_VOLTAGE

    session.channels[channel_name].voltage_level_autorange = True
    session.channels[channel_name].current_limit_autorange = True

    session.channels[channel_name].voltage_level = voltage_level
    session.channels[channel_name].current_limit = get_current_limit(voltage_level, current_limit, power_limit)
    session.channels[channel_name].source_delay = source_delay

    session.channels[channel_name].commit()
    session.channels[channel_name].initiate()

    session.channels[channel_name].wait_for_event(event_id=Event.SOURCE_COMPLETE)
    session.channels[channel_name].abort()
    return


# function to start load device and keep power sinking on
def initiate_load(
        session: Session,
        channel_name: str,
        current_level: float,
        voltage_limit_range: float,
        source_delay: float
) -> None:
    # configure the load session
    session.channels[channel_name].sense = Sense.REMOTE
    session.channels[channel_name].source_mode = SourceMode.SINGLE_POINT
    session.channels[channel_name].output_function = OutputFunction.DC_CURRENT

    session.channels[channel_name].current_level_autorange = True

    session.channels[channel_name].current_level = current_level
    session.channels[channel_name].voltage_limit_range = voltage_limit_range
    session.channels[channel_name].source_delay = source_delay

    session.channels[channel_name].commit()
    session.channels[channel_name].initiate()

    session.channels[channel_name].wait_for_event(event_id=Event.SOURCE_COMPLETE)
    session.channels[channel_name].abort()
    return


# function to configure source for perform measurement
def configure_source(
        session: Session,
        channel_name: str,
        voltage_levels: list[float],
        current_limit: float,
        power_limit: float,
        current_sweep_points: int,
        source_delay: float,
        aperture_time: float
) -> None:
    # configure the source session
    session.channels[channel_name].sense = Sense.REMOTE
    session.channels[channel_name].source_mode = SourceMode.SEQUENCE
    session.channels[channel_name].output_function = OutputFunction.DC_VOLTAGE

    session.channels[channel_name].voltage_level_autorange = True
    session.channels[channel_name].current_limit_autorange = True
    session.channels[channel_name].source_delay = source_delay

    session.channels[channel_name].create_advanced_sequence('SourceVoltages', ['voltage_level', 'current_limit'])

    for i in voltage_levels:
        for _ in range(current_sweep_points):
            session.channels[channel_name].create_advanced_sequence_step()
            session.channels[channel_name].voltage_level = i
            session.channels[channel_name].current_limit = get_current_limit(i, current_limit, power_limit)

    session.channels[channel_name].measure_when = MeasureWhen.AUTOMATICALLY_AFTER_SOURCE_COMPLETE
    session.channels[channel_name].aperture_time = aperture_time

    session.channels[channel_name].commit()
    return


# function to configure load for perform measurement
def configure_load(
        session: Session,
        channel_name: str,
        current_levels: list[float],
        voltage_limit_range: float,
        aperture_time: float,
        source_terminal_name: str,
        measure_terminal_name: str
) -> None:
    # configure the load session
    session.channels[channel_name].sense = Sense.REMOTE
    session.channels[channel_name].source_mode = SourceMode.SEQUENCE
    session.channels[channel_name].output_function = OutputFunction.DC_CURRENT

    session.channels[channel_name].current_level_autorange = True
    session.channels[channel_name].voltage_limit_range = voltage_limit_range
    session.channels[channel_name].set_sequence(current_levels, [0 for _ in range(len(current_levels))])

    session.channels[channel_name].source_trigger_type = TriggerType.DIGITAL_EDGE
    session.channels[channel_name].measure_trigger_type = TriggerType.DIGITAL_EDGE

    session.channels[channel_name].digital_edge_source_trigger_input_terminal = source_terminal_name
    session.channels[channel_name].measure_when = MeasureWhen.ON_MEASURE_TRIGGER
    session.channels[channel_name].aperture_time = aperture_time
    session.channels[channel_name].digital_edge_measure_trigger_input_terminal = measure_terminal_name

    session.channels[channel_name].commit()
    return


# function to perform measurements
def perform_measurements(
        source_session: Session,
        source_device_channel: str,
        load_session: Session,
        load_device_channel: str,
        voltage_values: list[float],
        load_sweep_points: int,
        nominal_output_voltage: float,
        load_currents: list[float],
        load_voltages: list[float],
        efficiency: list[float],
        load_voltage_deviation: list[float],
):
    for _ in voltage_values:
        for _ in range(load_sweep_points):
            source_measurement = source_session.channels[source_device_channel].fetch_multiple(count=1)[0]
            load_measurement = load_session.channels[load_device_channel].fetch_multiple(count=1)[0]
            load_currents.append(abs(load_measurement.current))
            load_voltages.append(load_measurement.voltage)
            efficiency.append(
                abs((load_voltages[-1]*load_currents[-1]*100) / (source_measurement.voltage*source_measurement.current))
            )
            load_voltage_deviation.append(
                ((load_voltages[-1] - nominal_output_voltage)/nominal_output_voltage)*100
            )
            yield
    yield
