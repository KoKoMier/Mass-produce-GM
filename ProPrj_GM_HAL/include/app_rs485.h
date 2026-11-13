#ifndef APP_RS485_H
#define APP_RS485_H

#include "stm32f1xx_hal.h"

HAL_StatusTypeDef AppRs485_Init(void);
HAL_StatusTypeDef AppRs485_SendMeasurements(
    uint32_t timestamp_ms,
    const uint32_t ck_cps_x100[3],
    const uint32_t adc_millivolts[3]);

#endif
