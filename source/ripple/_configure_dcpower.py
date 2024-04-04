import nidcpower


# Error handling with device reset added
def open_and_configure_dcpower_source(
        resource_name,
        channel_name,
        source_device_voltage_v,
        source_current_limit_a,
        source_channel_setup_time_s
):
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_VOLTAGE

        session.channels[channel_name].voltage_level = source_device_voltage_v
        session.channels[channel_name].current_limit = source_current_limit_a

        session.channels[channel_name].voltage_level_autorange = True
        session.channels[channel_name].current_limit_autorange = True
        session.channels[channel_name].source_delay = source_channel_setup_time_s
        session.channels[channel_name].measure_when = nidcpower.MeasureWhen.ON_DEMAND

        session.channels[channel_name].commit()
    except Exception as e:
        reset_dc_source(session, channel_name)
        raise e
    return session


# Error handling with device reset added
def open_and_configure_dcpower_load(
        resource_name,
        channel_name,
        load_device_current_a,
        load_voltage_limit_v,
        load_channel_setup_time_s
):
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_CURRENT

        session.channels[channel_name].current_level = load_device_current_a
        session.channels[channel_name].current_level_autorange = True
        session.channels[channel_name].voltage_limit_range = load_voltage_limit_v
        session.channels[channel_name].source_delay = load_channel_setup_time_s
        session.channels[channel_name].measure_when = nidcpower.MeasureWhen.ON_DEMAND

        session.channels[channel_name].commit()
    except Exception as e:
        reset_dc_source(session, channel_name)
        raise e
    return session


# Error handling with device reset added
def measure_dcpower(session, channel_name):
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


def close_dcpower(session, channel_name):
    session.channels[channel_name].abort()
    session.close()


# Error handling with device reset added
def power_on_dut(
        resource_name,
        channel_name,
        source_device_voltage_v,
        source_current_limit_a
):
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_VOLTAGE

        session.channels[channel_name].voltage_level = source_device_voltage_v
        session.channels[channel_name].current_limit = source_current_limit_a

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


def reset_dc_source(session, channel):
    session.channels[channel].output_enabled = False
    session.channels[channel].reset()
    session.close()
