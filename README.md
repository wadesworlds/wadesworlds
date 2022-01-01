- 👋 Hi, I’m @wadesworlds
   I'm learning Marlin. And making my first 3d printer from scratch. Its a Cartesian with a build plate 500 x 1000. It has a BTT SKR PRO 1.2 with 2209 steppers. 
-   X, Y,  Z split (r and L)  E0 (Extruder with mosquito hot end) Y2  The Y are split for two motors on each stepper. 
    Trying to use Software SPI for MAX31865 on the Extension 2 bus.
    PD2=SI
    PD5=DO
    PE0=CLK
    PE2=CS
    Having trouble with MAX31865 Adafruit for sensor. Have gone to every file in Marlin trying to find where I made a mistake.
    
    HERE is the Error:
    Compiling .pio\build\BIGTREE_SKR_PRO\src\src\HAL\STM32\MarlinSerial.cpp.o
Compiling .pio\build\BIGTREE_SKR_PRO\src\src\HAL\STM32\Sd2Card_sdio_stm32duino.cpp.o
Compiling .pio\build\BIGTREE_SKR_PRO\src\src\HAL\STM32\Servo.cpp.o
Compiling .pio\build\BIGTREE_SKR_PRO\src\src\HAL\STM32\eeprom_bl24cxx.cpp.o
Compiling .pio\build\BIGTREE_SKR_PRO\src\src\HAL\STM32\eeprom_flash.cpp.o
In file included from Marlin\src\HAL\STM32\../../inc/MarlinConfig.h:49,
                 from Marlin\src\HAL\STM32\HAL.cpp:30:
Marlin\src\HAL\STM32\../../inc/SanityCheck.h:2156:4: error: #error "TEMP_SENSOR_0 MAX thermocouple requires TEMP_0_CS_PIN."
 2156 |   #error "TEMP_SENSOR_0 MAX thermocouple requires TEMP_0_CS_PIN."
      |    ^~~~~
In file included from Marlin\src\HAL\STM32\../../inc/MarlinConfig.h:49,
                 from Marlin\src\HAL\STM32\MarlinSerial.cpp:27:
Marlin\src\HAL\STM32\../../inc/SanityCheck.h:2156:4: error: #error "TEMP_SENSOR_0 MAX thermocouple requires TEMP_0_CS_PIN."
 2156 |   #error "TEMP_SENSOR_0 MAX thermocouple requires TEMP_0_CS_PIN."
      |    ^~~~~
In file included from Marlin\src\HAL\STM32\../../inc/MarlinConfig.h:49,
                 from Marlin\src\HAL\STM32\HAL_SPI.cpp:27:


This is the frist time using GITHUB so do not know where to take this.

Thanks for your time in reading this.
