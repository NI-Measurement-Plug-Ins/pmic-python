import nidcpower


# function to reset SMU channel
def reset_dc_source(session: nidcpower.Session, channel: str):
    session.channels[channel].output_enabled = False
    session.channels[channel].reset()
    session.close()
    return


# function to measure DC levels of SMU
def measure_dcpower(session: nidcpower.Session, channel_name: str):
    try:
        with session.channels[channel_name].initiate():
            session.channels[channel_name].wait_for_event(event_id=nidcpower.Event.SOURCE_COMPLETE, timeout=5)
            measurements = session.channels[channel_name].measure_multiple()
        measurement = measurements[0]
        result = [measurement.voltage, measurement.current, session]
    except Exception as e:
        reset_dc_source(session, channel_name)
        raise e
    return result


# function to configure power supply SMU
def power_on_dut(
        resource_name: str,
        channel_name: str,
        source_device_voltage: float,
        source_current_limit: float
):
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_VOLTAGE

        session.channels[channel_name].voltage_level = source_device_voltage
        session.channels[channel_name].current_limit = source_current_limit

        session.channels[channel_name].voltage_level_autorange = True
        session.channels[channel_name].current_limit_autorange = True

        session.channels[channel_name].commit()
        result = measure_dcpower(session, channel_name)

        session.channels[channel_name].abort()
        session.close()
    except Exception as e:
        reset_dc_source(session, channel_name)
        raise e
    return result


# configure source SMU
def open_and_configure_dcpower_source(
        resource_name: str,
        channel_name: str,
        voltage_level: float,
        current_limit: float,
        dut_setup_time: float,
        aperture_time: float
):
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
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
    except Exception as e:
        reset_dc_source(session, channel_name)
        raise e
    return session


# configure load SMU
def open_and_configure_dcpower_load(
        resource_name: str,
        channel_name: str,
        current_level: float,
        voltage_limit_range: float,
        dut_setup_time: float,
        aperture_time: float
):
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_CURRENT

        session.channels[channel_name].current_level = current_level
        session.channels[channel_name].current_level_autorange = True
        session.channels[channel_name].voltage_limit_range = voltage_limit_range
        session.channels[channel_name].source_delay = dut_setup_time
        session.channels[channel_name].aperture_time = aperture_time
        session.channels[channel_name].measure_when = nidcpower.MeasureWhen.ON_DEMAND

        session.channels[channel_name].commit()
    except Exception as e:
        reset_dc_source(session, channel_name)
        raise e
    return session


# close dc power session
def close_dcpower(session, channel_name):
    session.channels[channel_name].abort()
    session.close()
    return


# close both source and load SMUs'
def power_off_dut(
        source_resource_name,
        source_channel_name,
        load_resource_name,
        load_channel_name
):

    load_session = nidcpower.Session(resource_name=load_resource_name, channels=load_channel_name)
    load_session.channels[load_channel_name].output_enabled = False
    load_session.channels[load_channel_name].reset()
    load_session.close()

    source_session = nidcpower.Session(resource_name=source_resource_name, channels=source_channel_name)
    source_session.channels[source_channel_name].output_enabled = False
    source_session.channels[source_channel_name].reset()
    source_session.close()
    return
