import nidcpower


# function to configure source SMU
def open_and_configure_dcpower_source(
        resource_name: str,
        channel_name: str,
        voltage_level: float,
        current_limit: float,
        dut_setup_time: float,
        aperture_time: float
):
    # Open the session
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
        # configure the session
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_VOLTAGE

        session.channels[channel_name].voltage_level = voltage_level
        session.channels[channel_name].current_limit = current_limit

        session.channels[channel_name].voltage_level_autorange = True
        session.channels[channel_name].current_limit_autorange = True
        session.channels[channel_name].source_delay = dut_setup_time
        session.channels[channel_name].aperture_time = aperture_time
        session.channels[channel_name].measure_when = nidcpower.MeasureWhen.ON_DEMAND

        session.channels[channel_name].commit()
        return session

    except nidcpower.Error:
        session.output_enabled = False
        session.reset()
        session.close()
        raise


# function to configure load SMU
def open_and_configure_dcpower_load(
        resource_name: str,
        channel_name: str,
        current_level: float,
        voltage_limit_range: float,
        dut_setup_time: float,
        aperture_time: float
):
    # Open the session
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:

        # configure the session
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_CURRENT

        session.configure_aperture_time(aperture_time, units=nidcpower.ApertureTimeUnits.SECONDS)

        session.channels[channel_name].current_level = current_level
        session.channels[channel_name].current_level_autorange = True
        session.channels[channel_name].voltage_limit_range = voltage_limit_range
        session.channels[channel_name].source_delay = dut_setup_time
        session.channels[channel_name].aperture_time = aperture_time
        session.channels[channel_name].measure_when = nidcpower.MeasureWhen.ON_DEMAND

        session.channels[channel_name].commit()
        return session

    except nidcpower.Error:
        session.output_enabled = False
        session.reset()
        session.close()
        raise


# function to measure dc power levels
def measure_dcpower(session: nidcpower.Session, channel_name: str):
    try:

        with session.channels[channel_name].initiate():
            session.channels[channel_name].wait_for_event(event_id=nidcpower.Event.SOURCE_COMPLETE, timeout=5)
            measurements = session.channels[channel_name].measure_multiple()

        measurement = measurements[0]
        result = [measurement.voltage, measurement.current, session]
        return result

    except nidcpower.Error:
        session.output_enabled = False
        session.reset()
        session.close()
        raise


# function to measure multiple voltage points
def measure_voltage(session: nidcpower.Session, channel_name: str, no_of_samples_to_fetch: int):
    try:
        session.measure_record_length = no_of_samples_to_fetch
        session.measure_record_length_is_finite = True
        session.channels[channel_name].measure_when = nidcpower.MeasureWhen.AUTOMATICALLY_AFTER_SOURCE_COMPLETE
        session.commit()

        volts = []
        with session.channels[channel_name].initiate():

            samples_acquired = 0
            while samples_acquired < no_of_samples_to_fetch:
                measurements = session.channels[channel_name].fetch_multiple(count=session.fetch_backlog)
                samples_acquired += len(measurements)

                for i in range(len(measurements)):
                    volts.append(measurements[i].voltage)

        return volts

    except nidcpower.Error:
        session.output_enabled = False
        session.reset()
        session.close()
        raise


# function to close dc power session
def close_dcpower(session: nidcpower.Session, channel_name: str):
    session.channels[channel_name].abort()
    session.close()


# function to configure source SMU
def power_on_dut(
        resource_name: str,
        channel_name: str,
        voltage_level: float,
        current_limit: float
):
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
        # configure the session
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_VOLTAGE

        session.channels[channel_name].voltage_level = voltage_level
        session.channels[channel_name].current_limit = current_limit

        session.channels[channel_name].voltage_level_autorange = True
        session.channels[channel_name].current_limit_autorange = True

        session.channels[channel_name].commit()
        result = measure_dcpower(session, channel_name)

        session.channels[channel_name].abort()
        # check for error and reset channel
        session.close()
        return result

    except nidcpower.Error:
        session.output_enabled = False
        session.reset()
        session.close()
        raise


# function to power off source and load SMUs'
def power_off_dut(
        source_resource_name: str,
        source_channel_name: str,
        load_resource_name: str,
        load_channel_name: str
):
    load_session = nidcpower.Session(resource_name=load_resource_name, channels=load_channel_name)
    load_session.channels[load_channel_name].output_enabled = False
    load_session.channels[load_channel_name].reset()
    load_session.close()

    source_session = nidcpower.Session(resource_name=source_resource_name, channels=source_channel_name)
    source_session.channels[source_channel_name].output_enabled = False
    source_session.channels[source_channel_name].reset()
    source_session.close()
