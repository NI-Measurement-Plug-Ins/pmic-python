#TODO:
# - channel_list() function - consider including parameter for Slave-Inverted? 
# - Check Channel List subVI in Ganged Initialize - is it needed?
# - configure_triggers() function - better way to slice/access slave resources?
# - Add 'Manual' case for measure_multiple() function?
# - Check complete Channel Ganging library and ensure all functions are translated here
# - Comment stuff. Linting?

"""Helpers for controlling multiple NI-DCPower sessions as one logical ganged output.

Ganging modes:
- Parallel: total current is split across channels when sourcing current-related setpoints.
- Series: total voltage is split across channels when sourcing voltage-related setpoints.

Trigger model:
- One channel is designated as MASTER.
- Slave channels follow master source and measure triggers through digital-edge terminals.

Conventions:
- Channel name is currently fixed to "0" in channel_list().
- Per-channel sign inversion is supported through ChannelMode.SLAVE_INVERTED.
"""

from concurrent.futures import ThreadPoolExecutor
from statistics import mean

from dataclasses import dataclass
from enum import Enum

from nidcpower import (
    Session, SourceMode, Sense, OutputFunction, MeasureWhen, TriggerType, Event, TransientResponse, ComplianceLimitSymmetry
)


class GangedConfig(Enum):
    SERIES = 0
    r'''
    The channels are ganged in series. The voltage level and voltage limit are divided by the number of channels in the ganged configuration.
    '''
    PARALLEL = 1
    r'''
    The channels are ganged in parallel. The current limit and current level are divided by the number of channels in the ganged configuration.
    '''
    pass


class ChannelMode(Enum):
    MASTER = 0
    r'''
    The channel is the master channel in the ganged configuration.
    The master channel is the channel that controls the source and measure triggers for all channels in the ganged configuration.
    '''
    SLAVE = 1
    r'''
    The channel is a slave channel in the ganged configuration.
    '''
    SLAVE_INVERTED = 2
    r'''
    The channel is a slave channel in the ganged configuration, and the output of the channel is inverted.
    '''
    pass


class SweepType(Enum):
    Linear = 0
    r'''
    The sweep is linear. The values are evenly spaced between the start and stop values.
    '''
    Logarithmic = 1
    r'''
    The sweep is logarithmic. The values are spaced logarithmically between the start and stop values.
    '''

    def __eq__(self, other):
        return self.value == other.value

    pass


class MeasurementSense(Enum):
    NONE = 0
    r'''
    Placeholder as ni_measurementlink_service expects a value of 0 in every Enum.
    '''
    LOCAL = Sense.LOCAL.value
    r'''
    The channel is configured to measure the voltage or current at the output terminals of the channel.
    '''
    REMOTE = Sense.REMOTE.value
    r'''
    The channel is configured to measure the voltage or current at the remote sense terminals of the channel.
    '''
    pass


class InstrumentTransientResponse(Enum):
    NONE = 0
    r'''
    Placeholder as ni_measurementlink_service expects a value of 0 in every Enum.
    '''
    CUSTOM = TransientResponse.CUSTOM.value
    r'''
    The channel is configured to use a custom transient response. The gain bandwidth, compensation frequency, and pole zero ratio are set by the user.
    '''
    SLOW = TransientResponse.SLOW.value
    r'''
    The channel is configured to use a slow transient response. The gain bandwidth, compensation frequency, and pole zero ratio are set by the instrument.
    '''
    NORMAL = TransientResponse.NORMAL.value
    r'''
    The channel is configured to use a normal transient response. The gain bandwidth, compensation frequency, and pole zero ratio are set by the instrument.
    '''
    FAST = TransientResponse.FAST.value
    r'''
    The channel is configured to use a fast transient response. The gain bandwidth, compensation frequency, and pole zero ratio are set by the instrument.
    '''


@dataclass
class ChannelList:
    """Describes one physical resource and its role in a ganged setup.

    Attributes:
        resource_name: NI resource descriptor, for example PXI1Slot3.
        channel_name: Channel identifier on the resource, typically "0".
        channel_mode: MASTER, SLAVE, or SLAVE_INVERTED.
    """
    resource_name: str
    channel_name: str
    channel_mode: ChannelMode


@dataclass
class GangedSession:
    """Container for sessions that operate as one logical ganged instrument.

    Attributes:
        ganged_config: Series or parallel ganging behavior.
        session_list: Open NI-DCPower Session objects.
        session_mode: Per-session role mapping aligned with session_list.
        channel: Per-session channel names aligned with session_list.
    """
    ganged_config: GangedConfig
    session_list: list[Session]
    session_mode: list[ChannelMode]
    channel: list[str]


def generate_sequence(
        sweep_type: Enum,
        start: float, stop: float,
        steps: int,
        with_end_points: bool = True
) -> list[float]:
    """Generate linear or logarithmic sweep values.

    Returns an empty list when the requested range is invalid or step count is non-positive.

    Args:
        sweep_type: Sweep progression type, linear or logarithmic.
        start: Sweep start value.
        stop: Sweep stop value.
        steps: Number of requested steps.
        with_end_points: Includes start/stop when True.

    Returns:
        List of generated sweep values.
    """
    res = []
    if start > stop or steps <= 0:
        return res

    if sweep_type == SweepType.Linear:
        if with_end_points:
            if (steps-1==0): d=0
            else: d = (stop - start) / (steps - 1)
            for i in range(steps):
                res.append((start + (i * d)))
            return res
        else:
            d = (stop - start) / (steps + 1)
            for i in range(steps + 2):
                res.append((start + (i * d)))
            return res[1:-1]
    else:
        if with_end_points:
            r = 10 ** (1 / (steps))
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
                    return res[1:-1]
    pass


def build_trigger_terminal(session: Session, channel_name: str, event_name: str) -> str:
    """Build a fully qualified trigger terminal path for a channel event."""
    resource_name = session.io_resource_descriptor
    if resource_name.find('/') != -1:
        resource_name = resource_name.split('/')[0]

    return f'/{resource_name}/Engine{channel_name}/{event_name}'


def channel_list(master_resource_name: str, slave_resource_names: list):
    """Create a master/slave channel configuration list for ganged operation."""
    master = ChannelList(resource_name=master_resource_name, channel_name="0", channel_mode=ChannelMode.MASTER)
    slaves = []
    for slave in slave_resource_names:
        slaves.append(ChannelList(resource_name=slave, channel_name="0", channel_mode=ChannelMode.SLAVE))

    return [master] + slaves


def initialize(channel_list: list[ChannelList], reset=False, ganged_config=GangedConfig.PARALLEL, options={}):
    """Create NI-DCPower sessions from channel configuration and wrap them in a ganged session.

    Args:
        channel_list: Channel definitions used to create sessions.
        reset: Resets each session at initialization when True.
        ganged_config: Ganging behavior, series or parallel.
        options: Driver options passed to each NI-DCPower session.

    Returns:
        A populated ganged session container.
    """
    session_list = []
    session_mode = []
    channel = []
    for resource in channel_list:
        session_list.append(Session(resource_name=resource.resource_name, channels=resource.channel_name, reset=reset, options=options))
        session_mode.append(resource.channel_mode)
        channel.append(resource.channel_name)
    
    return GangedSession(ganged_config=ganged_config, session_list=session_list, session_mode=session_mode, channel=channel)


def configure_source_mode(ganged_session: GangedSession, source_mode: SourceMode):
    """Set source mode for all channels in the ganged session."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].source_mode = source_mode
    
    return


def configure_sense(ganged_session: GangedSession, sense: Sense):
    """Set measurement sense mode for all channels in the ganged session."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].sense = sense
    
    return


def configure_output_function(ganged_session: GangedSession, output_function: OutputFunction):
    """Set output function for all channels in the ganged session."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].output_function = output_function
    
    return


def configure_voltage_level_range(ganged_session: GangedSession, voltage_level_range: float):
    """Configure voltage level range on all channels, scaling for series ganging."""
    if ganged_session.ganged_config == GangedConfig.SERIES:
        voltage_level_range /= len(ganged_session.session_list)

    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].voltage_level_range = voltage_level_range
    
    return


def configure_current_limit_range(ganged_session: GangedSession, current_limit_range: float):
    """Configure current limit range on all channels, scaling for parallel ganging."""
    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        current_limit_range /= len(ganged_session.session_list)
    
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].current_limit_range = current_limit_range
    
    return


def configure_current_limit(ganged_session: GangedSession, current_limit_hi: float, current_limit_lo: float, limit_symmetry: ComplianceLimitSymmetry):
    """Configure current compliance limits for all channels in the ganged session.

    Args:
        ganged_session: Target ganged NI-DCPower session.
        current_limit_hi: Positive or symmetric current limit value.
        current_limit_lo: Negative current limit value for asymmetric mode.
        limit_symmetry: Symmetric or asymmetric compliance-limit mode.
    """
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
    """Configure channel voltage levels with ganged scaling and slave inversion handling."""
    if ganged_session.ganged_config == GangedConfig.SERIES:
        voltage_level /= len(ganged_session.session_list)

    for session, channel, mode in zip(ganged_session.session_list, ganged_session.channel, ganged_session.session_mode):
        if mode == ChannelMode.SLAVE_INVERTED:
            voltage_level *= -1
        
        session.channels[channel].voltage_level = voltage_level
    
    return


def configure_voltage_limit(ganged_session: GangedSession, voltage_limit_hi: float, voltage_limit_lo: float, limit_symmetry: ComplianceLimitSymmetry):
    """Configure voltage compliance limits with ganged scaling and slave inversion handling.

    Args:
        ganged_session: Target ganged NI-DCPower session.
        voltage_limit_hi: Positive or symmetric voltage limit value.
        voltage_limit_lo: Negative voltage limit value for asymmetric mode.
        limit_symmetry: Symmetric or asymmetric compliance-limit mode.
    """
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
    """Configure voltage limit range on all channels, scaling for series ganging."""
    if ganged_session.ganged_config == GangedConfig.SERIES:
        voltage_limit_range /= len(ganged_session.session_list)
    
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].voltage_limit_range = voltage_limit_range
    
    return


def configure_current_level_range(ganged_session: GangedSession, current_level_range: float):
    """Configure current level range on all channels, scaling for parallel ganging."""
    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        current_level_range /= len(ganged_session.session_list)

    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].current_level_range = current_level_range
    
    return


def configure_current_level(ganged_session: GangedSession, current_level: float):
    """Configure channel current levels, scaling for parallel ganging."""
    if ganged_session.ganged_config == GangedConfig.PARALLEL:
        current_level /= len(ganged_session.session_list)

    for session, channel in zip(ganged_session.session_list, ganged_session.channel):        
        session.channels[channel].current_level = current_level
    
    return


def output_enabled(ganged_session: GangedSession, output_enabled: bool):
    """Enable or disable output on all channels in the ganged session."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].output_enabled = output_enabled
    
    return


def configure_triggers(ganged_session: GangedSession, measure_when: MeasureWhen=MeasureWhen.AUTOMATICALLY_AFTER_SOURCE_COMPLETE):
    """Route source and measure triggers from the master channel to slave channels."""
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
    """Commit pending configuration changes on all channels."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].commit()
    
    return


def initiate(ganged_session: GangedSession):
    """Initiate all channels in reverse order to start the output sequence."""
    for session, channel in zip(ganged_session.session_list[::-1], ganged_session.channel[::-1]):
        session.channels[channel].initiate()
    
    return


def wait_for_event(ganged_session: GangedSession, event: Event=Event.SOURCE_COMPLETE, timeout: float=10.0):
    """Wait for an NI-DCPower event on all channels using parallel worker threads."""
    with ThreadPoolExecutor(max_workers=len(ganged_session.session_list)) as executor:
        futures = [
            executor.submit(session.channels[channel].wait_for_event, event_id=event, timeout=timeout)
            for session, channel in zip(ganged_session.session_list, ganged_session.channel)
        ]

        for future in futures:
            future.result()
    
    return


def abort(ganged_session: GangedSession):
    """Abort generation on all channels using parallel worker threads."""
    with ThreadPoolExecutor(max_workers=len(ganged_session.session_list)) as executor:
        futures = [
            executor.submit(session.channels[channel].abort)
            for session, channel in zip(ganged_session.session_list, ganged_session.channel)
        ]

        for future in futures:
            future.result()
    
    return

def set_sequence(ganged_session: GangedSession, values: list[float], source_delays: float=None, output_function: OutputFunction=None):   
    """Configure source sequence values and delays for all channels.

    Values are scaled to per-channel values for parallel current sweeps and series voltage sweeps.

    Args:
        ganged_session: Target ganged NI-DCPower session.
        values: Sequence of ganged-level source values.
        source_delays: Delay in seconds applied per sequence point.
        output_function: Output mode used to determine sequence scaling.

    Notes:
        When source_delays is None, each point defaults to 16.67e-3 seconds.
        In parallel mode with DC_CURRENT, values are divided by channel count.
        In series mode with DC_VOLTAGE, values are divided by channel count.
    """
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
    """Configure the master channel source trigger to a digital-edge terminal."""
    master_index = ganged_session.session_mode.index(ChannelMode.MASTER)
    master_session = ganged_session.session_list[master_index]
    master_channel = ganged_session.channel[master_index]

    master_session.channels[master_channel].source_trigger_type = TriggerType.DIGITAL_EDGE
    master_session.channels[master_channel].digital_edge_source_trigger_input_terminal = input_terminal

    return


def configure_digital_edge_measure_trigger(ganged_session: GangedSession, input_terminal: str):
    """Configure the master channel measure trigger to a digital-edge terminal."""
    master_index = ganged_session.session_mode.index(ChannelMode.MASTER)
    master_session = ganged_session.session_list[master_index]
    master_channel = ganged_session.channel[master_index]

    master_session.channels[master_channel].measure_trigger_type = TriggerType.DIGITAL_EDGE
    master_session.channels[master_channel].digital_edge_measure_trigger_input_terminal = input_terminal

    return


def measure_multiple(ganged_session: GangedSession, count: int=1, timeout: float=1.0) -> tuple[float, float, list, list]:
    """Fetch voltage/current measurements and combine them into ganged equivalents.

    Returns ganged voltage, ganged current, and per-channel voltage/current lists.

    Args:
        ganged_session: Target ganged NI-DCPower session.
        count: Number of measurements to fetch per channel.
        timeout: Fetch timeout in seconds.

    Returns:
        Tuple of ganged voltage, ganged current, per-channel voltages, and per-channel currents.

    Notes:
        For parallel ganging, ganged voltage is the mean and ganged current is the sum.
        For series ganging, ganged voltage is the sum and ganged current is the mean.
    """
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


def fetch_multiple(ganged_session: GangedSession, count: int=1, timeout: float=1.0) -> tuple[list[float], list[float]]:
    """Fetch waveform measurements and combine channels into ganged waveforms.

    Args:
        ganged_session: Target ganged NI-DCPower session.
        count: Number of samples to fetch per channel.
        timeout: Fetch timeout in seconds.

    Returns:
        Tuple of (ganged_voltages, ganged_currents), each a list of sample values.

    Notes:
        Parallel ganging: voltage is channel mean, current is channel sum.
        Series ganging: voltage is channel sum, current is channel mean.
    """
    per_channel_voltages: list[list[float]] = []
    per_channel_currents: list[list[float]] = []

    for session, channel, mode in zip(ganged_session.session_list, ganged_session.channel, ganged_session.session_mode):
        measurements = session.channels[channel].fetch_multiple(count=count, timeout=timeout)
        channel_voltages = [measurement.voltage for measurement in measurements]
        channel_currents = [measurement.current for measurement in measurements]

        if mode == ChannelMode.SLAVE_INVERTED:
            channel_currents = [-current for current in channel_currents]

        per_channel_voltages.append(channel_voltages)
        per_channel_currents.append(channel_currents)

    if not per_channel_voltages:
        return [], []

    sample_count = min(len(channel_voltages) for channel_voltages in per_channel_voltages)
    ganged_voltage_measurements: list[float] = []
    ganged_current_measurements: list[float] = []

    for sample_index in range(sample_count):
        sample_voltages = [channel_voltages[sample_index] for channel_voltages in per_channel_voltages]
        sample_currents = [channel_currents[sample_index] for channel_currents in per_channel_currents]

        if ganged_session.ganged_config == GangedConfig.PARALLEL:
            ganged_voltage_measurements.append(mean(sample_voltages))
            ganged_current_measurements.append(sum(sample_currents))
        elif ganged_session.ganged_config == GangedConfig.SERIES:
            ganged_voltage_measurements.append(sum(sample_voltages))
            ganged_current_measurements.append(mean(sample_currents))

    return ganged_voltage_measurements, ganged_current_measurements


def output_connected(ganged_session: GangedSession, output_connected: bool):
    """Connect or disconnect output relays for all channels in parallel."""
    with ThreadPoolExecutor(max_workers=len(ganged_session.session_list)) as executor:
        futures = [
            executor.submit(setattr, session.channels[channel], "output_connected", output_connected)
            for session, channel in zip(ganged_session.session_list, ganged_session.channel)
        ]

        for future in futures:
            future.result()
    
    return


def reset(ganged_session: GangedSession):
    """Reset all channels in the ganged session to instrument defaults."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].reset()
    
    return


def close(ganged_session: GangedSession):
    """Close all NI-DCPower sessions in the ganged session."""
    for session in ganged_session.session_list:
        session.close()
    
    return


def configure_transient_response(
        ganged_session: GangedSession,
        response: TransientResponse,
        output_function: OutputFunction,
        gain_bandwidth: float,
        compensation_frequency: float,
        pole_zero_ratio: float
):
    """Configure transient-response tuning parameters for voltage or current output mode.

    Args:
        ganged_session: Target ganged NI-DCPower session.
        response: Requested transient response profile.
        output_function: Selects voltage or current function.
        gain_bandwidth: Gain-bandwidth value in hertz. Higher values give faster response, but may cause overshoot or oscillation.
        compensation_frequency: Compensation-frequency value in hertz. Frequency of maximum phase shift caused by the pole-zero pair.
        pole_zero_ratio: Pole-zero ratio value (unitless). Ratio of the pole frequency to the zero frequency. A value of 1.0 means the pole and zero are at the same frequency, which gives a flat frequency response. A value less than 1.0 means the pole is at a lower frequency than the zero, which gives a faster response but may cause overshoot or oscillation. A value greater than 1.0 means the pole is at a higher frequency than the zero, which gives a slower response but may reduce overshoot or oscillation.
    """
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].transient_response = response
        if response == TransientResponse.CUSTOM:
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
    """Set source delay for all channels in the ganged session."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].source_delay = source_delay
    
    return


def configure_aperture_time(ganged_session: GangedSession, aperture_time: float):
    """Set aperture time for all channels in the ganged session."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].aperture_time = aperture_time
    
    return


def configure_measure_record_length(ganged_session: GangedSession, record_length: int):
    """Set measure record length for all channels in the ganged session."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].measure_record_length = record_length
    
    return

def configure_slew_rate(ganged_session: GangedSession, rising_slew_rate: float, falling_slew_rate: float):
    """Set rising and falling slew rates for all channels in the ganged session."""
    for session, channel in zip(ganged_session.session_list, ganged_session.channel):
        session.channels[channel].current_level_rising_slew_rate = rising_slew_rate
        session.channels[channel].current_level_falling_slew_rate = falling_slew_rate
    
    return
