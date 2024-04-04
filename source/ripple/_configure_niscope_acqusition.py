import hightime
import niscope


def perform_scope_acquisition(
        scope_resource_name,
        scope_channel_name,
        scope_probe_attenuation,
        scope_sample_rate,
        scope_acquisition_time,
        ripple_graph
):
    input_impedance = 1000000  # 1 mega ohm

    with niscope.Session(scope_resource_name) as session:
        session.channels[scope_channel_name].configure_vertical(
            range=5.0,
            offset=0.0,
            probe_attenuation=scope_probe_attenuation,
            coupling=niscope.VerticalCoupling.AC
        )
        session.channels[scope_channel_name].configure_chan_characteristics(
            input_impedance=input_impedance,
            max_input_frequency=-1
        )

        session.trigger_modifier = niscope.TriggerModifier.AUTO
        session.configure_trigger_edge(
            trigger_source=scope_channel_name,
            level=0,
            trigger_coupling=niscope.TriggerCoupling.DC,
            slope=niscope.TriggerSlope.POSITIVE
        )

        session.configure_horizontal_timing(
            min_sample_rate=scope_sample_rate,
            min_num_pts=int(scope_sample_rate*scope_acquisition_time),
            ref_position=0,
            num_records=1,
            enforce_realtime=True
        )

        with session.initiate():
            waveforms = session.channels[scope_channel_name].fetch(
                num_samples=int(scope_sample_rate * scope_acquisition_time),
                timeout=hightime.timedelta(scope_acquisition_time+5.0)
            )

        if waveforms:
            waveform_info = waveforms[0]
            ripple_voltages = list(waveform_info.samples)

        t = 0
        dt = 1 / session.horz_sample_rate
        for i in ripple_voltages:
            ripple_graph.x_data.append(t)
            ripple_graph.y_data.append(i)
            t += dt

    return ripple_voltages
