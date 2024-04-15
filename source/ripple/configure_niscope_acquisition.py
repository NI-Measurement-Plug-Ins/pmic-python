import hightime
import niscope
from ni_measurementlink_service._internal.stubs.ni.protobuf.types.xydata_pb2 import DoubleXYData


# configure scope device
def perform_scope_acquisition(
        resource_name: str,
        channel_name: str,
        sample_rate: float,
        acquisition_time: float,
        probe_attenuation: float,
        ripple_voltages: list[float],
        ripple_graph: DoubleXYData
):
    input_impedance = 1000000  # 1 mega ohm
    t = 0

    with niscope.Session(resource_name) as session:
        session.channels[channel_name].configure_vertical(
            range=5.0,
            offset=0.0,
            probe_attenuation=probe_attenuation,
            coupling=niscope.VerticalCoupling.AC
        )
        session.channels[channel_name].configure_chan_characteristics(
            input_impedance=input_impedance,
            max_input_frequency=-1
        )

        session.trigger_modifier = niscope.TriggerModifier.AUTO
        session.configure_trigger_edge(
            trigger_source=channel_name,
            level=0,
            trigger_coupling=niscope.TriggerCoupling.DC,
            slope=niscope.TriggerSlope.POSITIVE
        )

        session.configure_horizontal_timing(
            min_sample_rate=sample_rate,
            min_num_pts=int(sample_rate * acquisition_time),
            ref_position=0,
            num_records=1,
            enforce_realtime=True
        )

        while acquisition_time > 0:
            with session.initiate():
                waveforms = session.channels[channel_name].fetch(
                    num_samples=int(sample_rate * (1 if (acquisition_time > 1) else acquisition_time)),
                    timeout=hightime.timedelta(acquisition_time * 2)
                )

            if waveforms:
                waveform_info = waveforms[0]
                ripples = list(waveform_info.samples)
                ripple_voltages.extend(ripples)

            dt = 1 / session.horz_sample_rate
            for i in ripples:
                ripple_graph.x_data.append(t)
                ripple_graph.y_data.append(i)
                t += dt

            acquisition_time -= 1
            yield ripple_voltages
