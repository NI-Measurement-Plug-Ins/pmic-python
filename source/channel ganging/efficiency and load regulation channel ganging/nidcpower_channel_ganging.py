#TODO:
# - wait_for_event() function - figure out how this works for ganged, LV uses a parallel For, this might be needed here as well
# - Above also true for function(s): abort(), output_connected()
# - measure_multiple() requires 'yield' instead of 'return'?
# - Error handling
# - channel_list() function - consider including parameter for Slave-Inverted? 
# - Check Channel List subVI in Ganged Initialize - is it needed?
# - configure_triggers() function - better way to slice/access slave resources?
# - Add 'Manual' case for measure_multiple() function?
# - Check complete Channel Ganging library and ensure all functions are translated here
# - Comment stuff. Linting?

from concurrent.futures import ThreadPoolExecutor
from statistics import mean

from dataclasses import dataclass
from enum import Enum

from nidcpower import (
    Session, SourceMode, Sense, OutputFunction, MeasureWhen, TriggerType, Event, TransientResponse, ComplianceLimitSymmetry
)


class GangedConfig(Enum):
    SERIES = 0
    PARALLEL = 1
    pass


class ChannelMode(Enum):
    MASTER = 0
    SLAVE = 1
    SLAVE_INVERTED = 2
    pass


# class LimitSymmetry(Enum):
#     NONE = 0
#     SYMMETRIC = ComplianceLimitSymmetry.SYMMETRIC.value
#     ASYMMETRIC = ComplianceLimitSymmetry.ASYMMETRIC.value
#     pass


class MeasurementSense(Enum):
    NONE = 0
    LOCAL = Sense.LOCAL.value
    REMOTE = Sense.REMOTE.value
    pass


class InstrumentTransientResponse(Enum):
    NONE = 0
    CUSTOM = TransientResponse.CUSTOM.value
    SLOW = TransientResponse.SLOW.value
    NORMAL = TransientResponse.NORMAL.value
    FAST = TransientResponse.FAST.value


@dataclass
class ChannelList:
    resource_name: str
    channel_name: str
    channel_mode: ChannelMode


@dataclass
class GangedSession:
    ganged_config: GangedConfig
    session_list: list[Session]
    session_mode: list[ChannelMode]
    channel: list[str]


def build_trigger_terminal(session: Session, channel_name: str, event_name: str) -> str:
    resource_name = session.io_resource_descriptor
    if resource_name.find('/') != -1:
        resource_name = resource_name.split('/')[0]

    return f'/{resource_name}/Engine{channel_name}/{event_name}'


def channel_list(master_resource_name: str, slave_resource_names: list):
    master = ChannelList(resource_name=master_resource_name, channel_name="0", channel_mode=ChannelMode.MASTER)
    slaves = []
    for slave in slave_resource_names:
        slaves.append(ChannelList(resource_name=slave, channel_name="0", channel_mode=ChannelMode.SLAVE))

    return [master] + slaves


def initialize(channel_list: list[ChannelList], reset=False, ganged_config=GangedConfig.PARALLEL, options={}):
    session_list = []
    session_mode = []
    channel = []
    for resource in channel_list:
        session_list.append(Session(resource_name=resource.resource_name, channels=resource.channel_name, reset=reset, options=options))
        session_mode.append(resource.channel_mode)
        channel.append(resource.channel_name)
    
    return GangedSession(ganged_config=ganged_config, session_list=session_list, session_mode=session_mode, channel=channel)


def configure_source_mode(ganged_session: GangedSession, source_mode: SourceMode):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].source_mode = source_mode
    
    return


def configure_sense(ganged_session: GangedSession, sense: Sense):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].sense = sense
    
    return


def configure_output_function(ganged_session: GangedSession, output_function: OutputFunction):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].output_function = output_function
    
    return


def configure_voltage_level_range(ganged_session: GangedSession, voltage_level_range: float):
    if ganged_session.ganged_config == GangedConfig.SERIES:
        voltage_level_range /= len(ganged_session.session_list)

    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].voltage_level_range = voltage_level_range
    
    return


def configure_current_limit_range(ganged_session: GangedSession, current_limit_range: float):
    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        current_limit_range /= len(ganged_session.session_list)
    
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].current_limit_range = current_limit_range
    
    return


def configure_current_limit(ganged_session: GangedSession, current_limit_hi: float, current_limit_lo: float, limit_symmetry: ComplianceLimitSymmetry):
    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        current_limit_hi /= len(ganged_session.session_list)
        current_limit_lo /= len(ganged_session.session_list)

    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].compliance_limit_symmetry = limit_symmetry
        if limit_symmetry == ComplianceLimitSymmetry.ASYMMETRIC:
            session.channels[channel].current_limit_high = current_limit_hi
            session.channels[channel].current_limit_low = current_limit_lo
        else:
            session.channels[channel].current_limit = current_limit_hi
    
    return


def configure_voltage_level(ganged_session: GangedSession, voltage_level: float):
    if ganged_session.ganged_config == GangedConfig.SERIES:
        voltage_level /= len(ganged_session.session_list)

    for session, channel, mode in zip(ganged_session.session_list, ganged_session.channel, ganged_session.session_mode):
        if mode == ChannelMode.SLAVE_INVERTED:
            voltage_level *= -1
        
        session.channels[channel].voltage_level = voltage_level
    
    return


def configure_voltage_limit(ganged_session: GangedSession, voltage_limit_hi: float, voltage_limit_lo: float, limit_symmetry: ComplianceLimitSymmetry):
    if ganged_session.ganged_config == GangedConfig.SERIES:
        voltage_limit_hi /= len(ganged_session.session_list)
        voltage_limit_lo /= len(ganged_session.session_list)

    for session, channel, mode in zip(ganged_session.session_list, ganged_session.channel, ganged_session.session_mode):
        if mode == ChannelMode.SLAVE_INVERTED:
            voltage_limit_hi *= -1
            voltage_limit_lo *= -1

        session.channels[channel].compliance_limit_symmetry = limit_symmetry
        if limit_symmetry == ComplianceLimitSymmetry.ASYMMETRIC:
            session.channels[channel].voltage_limit_high = voltage_limit_hi
            session.channels[channel].voltage_limit_low = voltage_limit_lo
        else:
            session.channels[channel].voltage_limit = voltage_limit_hi
    
    return


def configure_voltage_limit_range(ganged_session: GangedSession, voltage_limit_range: float):
    if ganged_session.ganged_config == GangedConfig.SERIES:
        voltage_limit_range /= len(ganged_session.session_list)
    
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].voltage_limit_range = voltage_limit_range
    
    return


def configure_current_level_range(ganged_session: GangedSession, current_level_range: float):
    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        current_level_range /= len(ganged_session.session_list)

    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].current_level_range = current_level_range
    
    return


def configure_current_level(ganged_session: GangedSession, current_level: float):
    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        current_level /= len(ganged_session.session_list)

    for session, channel in zip(ganged_session.session_list, ganged_session.channel):        
        session.channels[channel].current_level = current_level
    
    return


def output_enabled(ganged_session: GangedSession, output_enabled: bool):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].output_enabled = output_enabled
    
    return


def configure_triggers(ganged_session: GangedSession, measure_when: MeasureWhen=MeasureWhen.AUTOMATICALLY_AFTER_SOURCE_COMPLETE):
    master_index = ganged_session.session_mode.index(ChannelMode.MASTER)
    master_session = ganged_session.session_list[master_index]
    master_channel = ganged_session.channel[master_index]

    source_terminal_name = build_trigger_terminal(master_session, master_channel, "SourceTrigger")
    measure_terminal_name = build_trigger_terminal(master_session, master_channel, "MeasureTrigger")
    master_session.channels[master_channel].measure_when = measure_when
    master_session.channels[master_channel].commit()

    for session, channel in zip(ganged_session.session_list[master_index+1:], ganged_session.channel[master_index+1:]):
        session.channels[channel].source_trigger_type = TriggerType.DIGITAL_EDGE
        session.channels[channel].digital_edge_source_trigger_input_terminal = source_terminal_name

        session.channels[channel].measure_trigger_type = TriggerType.DIGITAL_EDGE
        session.channels[channel].digital_edge_measure_trigger_input_terminal = measure_terminal_name

        session.channels[channel].measure_when = MeasureWhen.ON_MEASURE_TRIGGER
        session.channels[channel].commit()

    return


def commit(ganged_session: GangedSession):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].commit()
    
    return


def initiate(ganged_session: GangedSession):
    for session, channel in zip(ganged_session.session_list[::-1], ganged_session.channel[::-1]):
        session.channels[channel].initiate()
    
    return


def wait_for_event(ganged_session: GangedSession, event: Event=Event.SOURCE_COMPLETE, timeout: float=10.0):
    with ThreadPoolExecutor(max_workers=len(ganged_session.session_list)) as executor:
        futures = [
            executor.submit(session.channels[channel].wait_for_event, event_id=event, timeout=timeout)
            for session, channel in zip(ganged_session.session_list, ganged_session.channel)
        ]

        for future in futures:
            future.result()
    
    return
    
    # CHECK TODO at the top, may need to implement parallel For


def abort(ganged_session: GangedSession):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].abort()
    
    return

def set_sequence(ganged_session: GangedSession, values: list[float], source_delays: float=None, output_function: OutputFunction=None):   
    if source_delays == None:
        source_delays = [16.67e-3 for i in range(len(values))]
    else:
        source_delays = [source_delays for i in range(len(values))]

    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        if output_function == OutputFunction.DC_CURRENT:
            values = [x / len(ganged_session.session_list) for x in values]
    else:
        if output_function == OutputFunction.DC_VOLTAGE:
            values = [x / len(ganged_session.session_list) for x in values]

    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].set_sequence(values=values, source_delays=source_delays)

    return


def configure_digital_edge_source_trigger(ganged_session: GangedSession, input_terminal: str):
    master_index = ganged_session.session_mode.index(ChannelMode.MASTER)
    master_session = ganged_session.session_list[master_index]
    master_channel = ganged_session.channel[master_index]

    master_session.channels[master_channel].source_trigger_type = TriggerType.DIGITAL_EDGE
    master_session.channels[master_channel].digital_edge_source_trigger_input_terminal = input_terminal

    return


def configure_digital_edge_measure_trigger(ganged_session: GangedSession, input_terminal: str):
    master_index = ganged_session.session_mode.index(ChannelMode.MASTER)
    master_session = ganged_session.session_list[master_index]
    master_channel = ganged_session.channel[master_index]

    master_session.channels[master_channel].measure_trigger_type = TriggerType.DIGITAL_EDGE
    master_session.channels[master_channel].digital_edge_measure_trigger_input_terminal = input_terminal

    return


def measure_multiple(ganged_session: GangedSession, count: int=1, timeout: float=1.0) -> tuple[float, float, list, list]:
    voltage_measurements = []
    current_measurements = []
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        measurements = session.channels[channel].fetch_multiple(count=count, timeout=timeout)

        for measurement in measurements:
            voltage_measurements.append(measurement.voltage)
            current_measurements.append(measurement.current)

    for i, (mode, current) in enumerate(zip(ganged_session.session_mode, current_measurements)):
        if mode == ChannelMode.SLAVE_INVERTED:
            current_measurements[i] = -current

    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        ganged_voltage_measurements = mean(voltage_measurements)
        ganged_current_measurements = sum(current_measurements)
    elif ganged_session.ganged_config == GangedConfig.SERIES:
        ganged_voltage_measurements = sum(voltage_measurements)
        ganged_current_measurements = mean(current_measurements)
    
    return ganged_voltage_measurements, ganged_current_measurements, voltage_measurements, current_measurements


def output_connected(ganged_session: GangedSession, output_connected: bool):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].output_connected = output_connected
    
    return


def reset(ganged_session: GangedSession):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].reset()
    
    return


def close(ganged_session: GangedSession):
    for session in ganged_session.session_list:
        session.close()
    
    return


def configure_transient_response(ganged_session: GangedSession, response: TransientResponse, output_function: OutputFunction, gain_bandwidth: float, compensation_frequency: float, pole_zero_ratio: float):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        if output_function == OutputFunction.DC_VOLTAGE:
            session.channels[channel].voltage_gain_bandwidth = gain_bandwidth
            session.channels[channel].voltage_compensation_frequency = compensation_frequency
            session.channels[channel].voltage_pole_zero_ratio = pole_zero_ratio
        elif output_function == OutputFunction.DC_CURRENT:
            session.channels[channel].current_gain_bandwidth = gain_bandwidth
            session.channels[channel].current_compensation_frequency = compensation_frequency
            session.channels[channel].current_pole_zero_ratio = pole_zero_ratio
        
        return


def configure_source_delay(ganged_session: GangedSession, source_delay: float):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].source_delay = source_delay
    
    return


def configure_aperture_time(ganged_session: GangedSession, aperture_time: float):
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].aperture_time = aperture_time
    
    return
    