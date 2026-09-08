# PSRR
This service performs PSRR measurement for PMIC.

## Hardware Setup
   ![alt text](meas-images/hw-setup-psrr.png)

## InstrumentStudio Panel
### Usage with Measurement UI Editor GUI
1. Select the appropriate source, load, scope and Fgen resource names and update other parameters as needed.
   Source and load Configuration
   ![alt text](meas-images/psrr-py-source-load-config.png)
   Fgen Configuration
   ![alt text](meas-images/psrr-python-fgen-config.png)
   Scope Configuration
   ![alt text](meas-images/psrr-python-scope-config.png)

 2. Run the measurement. PSRR graphs should be visible without any error.

    PSRR:
   ![alt text](meas-images/psrr-python-results.png) 

### Usage with LabVIEW GUI

1. Select the appropriate source, load, scope and Fgen resource names and update other parameters as needed.
   Source and load Configuration
   ![alt text](meas-images/psrr-lv-source-load-config.png)
   Fgen and Scope Configuration
   ![alt text](meas-images/psrr-lv-scope-fgen-config.png)

2. Run the measurement. PSRR graphs should be visible without any error.

   PSRR:
   ![alt text](meas-images/psrr-lv-results.png)
