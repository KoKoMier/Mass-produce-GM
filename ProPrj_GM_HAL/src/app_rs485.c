#include "app_rs485.h"

#include <stdio.h>

#define RS485_DE_PORT GPIOB
#define RS485_DE_PIN  GPIO_PIN_12

static UART_HandleTypeDef huart3;

HAL_StatusTypeDef AppRs485_Init(void)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_USART3_CLK_ENABLE();

    gpio.Pin = GPIO_PIN_10;
    gpio.Mode = GPIO_MODE_AF_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOB, &gpio);

    gpio.Pin = GPIO_PIN_11;
    gpio.Mode = GPIO_MODE_INPUT;
    gpio.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOB, &gpio);

    gpio.Pin = RS485_DE_PIN;
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(RS485_DE_PORT, &gpio);
    HAL_GPIO_WritePin(RS485_DE_PORT, RS485_DE_PIN, GPIO_PIN_RESET);

    huart3.Instance = USART3;
    huart3.Init.BaudRate = 115200;
    huart3.Init.WordLength = UART_WORDLENGTH_8B;
    huart3.Init.StopBits = UART_STOPBITS_1;
    huart3.Init.Parity = UART_PARITY_NONE;
    huart3.Init.Mode = UART_MODE_TX_RX;
    huart3.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart3.Init.OverSampling = UART_OVERSAMPLING_16;
    return HAL_UART_Init(&huart3);
}

HAL_StatusTypeDef AppRs485_SendMeasurements(
    uint32_t timestamp_ms,
    const uint32_t ck_cps_x100[3],
    const uint32_t adc_millivolts[3])
{
    char line[128];
    int length = snprintf(
        line,
        sizeof(line),
        "DATA,%lu,%lu.%02lu,%lu.%02lu,%lu.%02lu,%lu,%lu,%lu\r\n",
        (unsigned long)timestamp_ms,
        (unsigned long)(ck_cps_x100[0] / 100U),
        (unsigned long)(ck_cps_x100[0] % 100U),
        (unsigned long)(ck_cps_x100[1] / 100U),
        (unsigned long)(ck_cps_x100[1] % 100U),
        (unsigned long)(ck_cps_x100[2] / 100U),
        (unsigned long)(ck_cps_x100[2] % 100U),
        (unsigned long)adc_millivolts[0],
        (unsigned long)adc_millivolts[1],
        (unsigned long)adc_millivolts[2]);

    if ((length <= 0) || ((size_t)length >= sizeof(line))) return HAL_ERROR;

    HAL_GPIO_WritePin(RS485_DE_PORT, RS485_DE_PIN, GPIO_PIN_SET);
    HAL_StatusTypeDef status = HAL_UART_Transmit(
        &huart3, (uint8_t *)line, (uint16_t)length, 1000U);
    if (status == HAL_OK) {
        uint32_t start = HAL_GetTick();
        while (__HAL_UART_GET_FLAG(&huart3, UART_FLAG_TC) == RESET) {
            if ((HAL_GetTick() - start) >= 100U) {
                status = HAL_TIMEOUT;
                break;
            }
        }
    }
    HAL_GPIO_WritePin(RS485_DE_PORT, RS485_DE_PIN, GPIO_PIN_RESET);
    return status;
}
