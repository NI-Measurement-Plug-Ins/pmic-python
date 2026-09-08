# PSRR
This service performs PSRR measurement for PMIC.

## Hardware Setup
   ![alt text](meas-images/hw-setup-psrr.png)

## InstrumentStudio Panel

### Note:
By default, the application uses the LabVIEW GUI. If you want to switch to the Measurement UI Editor GUI, update the file name in measurement.py by modifying the ui_file_paths parameter as shown below: **ui_file_paths=[service_directory / "PSRR_PMIC.vi"]**

### Usage with LabVIEW GUI

1. Select the appropriate source, load, scope and Fgen resource names and update other parameters as needed.
   Source and load Configuration
   ![alt text](meas-images/psrr-lv-source-load-config.png)
   Fgen and Scope Configuration
   ![alt text](meas-images/psrr-lv-scope-fgen-config.png)

2. Run the measurement. PSRR graphs should be visible without any error.

   PSRR:
   ![alt text](meas-images/psrr-lv-results.png)

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

