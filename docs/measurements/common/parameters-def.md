# Parameters used in the measurements

## Measurement settings

1. DUT Setup Time:
   Specifies the setup time of a DUT, the time required to load the DUT parameters and for the DUT startup.

2. Aperture Time:
   Specifies the amount of time the source and load instruments collect samples and average the samples together to form a single measurement. Longer aperture time increases the test time but improves the noise rejection.

3. Nominal Output Voltage:
   Enter the expected nominal output voltage of the DUT. This value is used only for the calculation of load voltage deviation.

## Source configuration

#### Please refer to the device [specs](https://www.ni.com/docs/en-US/bundle/pxie-4151-specs/page/specs.html) for the current and voltage ranges.

1. Current Limit:
   Specifies the current limit of the source instrument for determining compliance.
   
2. Voltage Level:
   Specifies the voltage level of the source instrument.

## Load configuration

#### Please refer to the device [specs](https://www.ni.com/docs/en-US/bundle/pxie-4051-specs/page/specs.html) for the voltage and current ranges.

1. Voltage Limit Range:
   Specifies the voltage limit of the load instrument for determining compliance. 
  
2. Current Level:
   Specifies the current level of the load instrument. 

## Scope configuration

#### Please refer to the device [specs](https://www.ni.com/docs/en-US/bundle/pxie-5122-specs/page/specs.html) for the sample rate and timing values.

1. Sample rate:
   Specifies the sample rate of the scope instrument.

2. Acquisition time:
   Specifies the time duration for which scope acquires samples.

3. Probe attenuation:
   Specifies probe attenuation value of scope instrument.