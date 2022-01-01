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

Defined E0 CS to the Extention 2 CS Pin. 


#define E0_STEP_PIN                         PE14

#define E0_DIR_PIN                          PA0

#define E0_ENABLE_PIN                       PC3

#ifndef E0_CS_PIN

  #define E0_CS_PIN                         PE2
  
#endif


ONBOARD for SW_  is where you set the Software SPI for E0?

// Onboard SD card

// Must use soft SPI because Marlin's default hardware SPI is tied to LCD's EXP2

//

#if SD_CONNECTION_IS(LCD)



  #define SD_DETECT_PIN              EXP2_04_PIN
  
  #define SDSS                       EXP2_07_PIN
  

#elif SD_CONNECTION_IS(ONBOARD)


  // The SKR Pro's ONBOARD SD interface is on SPI1.
  
  // Due to a pull resistor on the clock line, it needs to use SPI Data Mode 3 to
  
  // function with Hardware SPI. This is not currently configurable in the HAL,
  
  // so force Software SPI to work around this issue.
  
  #define SOFTWARE_SPI
  
  #define SDSS                              PE2
  
  #define SD_SCK_PIN                        PE0
  
  #define SD_MISO_PIN                       PD5
  
  
  #define SD_MOSI_PIN                       PD2
  
  #define SD_DETECT_PIN                     PD0
  



This is the frist time using GITHUB so do not know where to take this.

Thanks for your time in reading this.
