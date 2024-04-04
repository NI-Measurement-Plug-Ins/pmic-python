import nidcpower

def open_and_configure_dcpower_source(
        resource_name,
        channel_name,
        source_device_voltage_v,
        source_current_limit_a,
        source_channel_setup_time_s
): 
    # Open the session
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:
        # configure the session
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
        return session
    
    except nidcpower.Error as e:
        print(f"Error Configuring DC Power Source: {e}")
        session.output_enabled = False
        session.reset()
        session.close()
        raise
 
def open_and_configure_dcpower_load(
        resource_name,
        channel_name,
        load_device_current_a,
        load_voltage_limit_v,
        aperture_time,
        load_channel_setup_time_s
):
    # Open the session
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)
    try:

        # configure the session
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_CURRENT
        
        session.configure_aperture_time(aperture_time, units=nidcpower.ApertureTimeUnits.SECONDS)

        session.channels[channel_name].current_level = load_device_current_a
        session.channels[channel_name].current_level_autorange = True
        session.channels[channel_name].voltage_limit_range = load_voltage_limit_v
        session.channels[channel_name].source_delay = load_channel_setup_time_s
        session.channels[channel_name].measure_when = nidcpower.MeasureWhen.ON_DEMAND

        session.channels[channel_name].commit()
        return session
    
    except nidcpower.Error as e:
        print(f"Error Configuring DC Power Load: {e}")
        session.output_enabled = False
        session.reset()
        session.close()
        raise   

def measure_dcpower(session, channel_name):

    try:

        with session.channels[channel_name].initiate():
            session.channels[channel_name].wait_for_event(event_id=nidcpower.Event.SOURCE_COMPLETE, timeout=5)
            measurements = session.channels[channel_name].measure_multiple()
        
        measurement = measurements[0]
        result = [measurement.voltage, measurement.current, session]
        return result

    except nidcpower.Error as e:
        print(f"Error : {e}")
        session.output_enabled = False
        session.reset()
        session.close()
        raise   




def measure_voltage(session, channel_name, no_of_samples_to_fetch):
    try:
        session.measure_record_length = no_of_samples_to_fetch
        session.measure_record_length_is_finite = True
        session.channels[channel_name].measure_when = nidcpower.MeasureWhen.AUTOMATICALLY_AFTER_SOURCE_COMPLETE
        session.commit()

        volts=[]
        with session.channels[channel_name].initiate():

            samples_acquired = 0
            while samples_acquired < no_of_samples_to_fetch:
                measurements = session.channels[channel_name].fetch_multiple(count=session.fetch_backlog)
                samples_acquired += len(measurements)

                for i in range(len(measurements)):
                    volts.append(measurements[i].voltage)
        
        return volts
    
    except nidcpower.Error as e:
        print(f"Error performing measurement: {e}")
        session.output_enabled = False
        session.reset()
        session.close()
        raise   


def close_dcpower(session, channel_name):

    session.channels[channel_name].abort()
    session.close()

def power_on_dut(
        resource_name,
        source_device_voltage_v,
        source_current_limit_a
):
    channel_name =  '0'
    session = nidcpower.Session(resource_name=resource_name, channels=channel_name)

    try:
        
        # configure the session
        session.channels[channel_name].sense = nidcpower.Sense.REMOTE
        session.channels[channel_name].source_mode = nidcpower.SourceMode.SINGLE_POINT
        session.channels[channel_name].output_function = nidcpower.OutputFunction.DC_VOLTAGE

        session.channels[channel_name].voltage_level = source_device_voltage_v
        session.channels[channel_name].current_limit = source_current_limit_a

        session.channels[channel_name].voltage_level_autorange = True
        session.channels[channel_name].current_limit_autorange = True

        session.channels[channel_name].commit()
        result =  measure_dcpower(session, channel_name)

        session.channels[channel_name].abort()
        # check for error and reset channel
        session.close()
        return result
    
    except nidcpower.Error as e:
        print(f"Error opening and configuring DC power source: {e}")
        session.output_enabled = False
        session.reset()
        session.close()
        raise   

def power_off_dut(
        source_resource_name,
        load_resource_name
):
    source_channel_name = '0'
    load_channel_name = '0'

    load_session = nidcpower.Session(resource_name=load_resource_name, channels=load_channel_name)
    load_session.channels[load_channel_name].output_enabled = False
    load_session.channels[load_channel_name].reset()
    load_session.close()

    source_session =  nidcpower.Session(resource_name=source_resource_name, channels=source_channel_name)
    source_session.channels[source_channel_name].output_enabled = False
    source_session.channels[source_channel_name].reset()
    source_session.close()