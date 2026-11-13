#include "stm32f1xx_hal.h"

#define PWM1_PULSE 158U /* PB0 / TIM3_CH3 */
#define PWM2_PULSE 159U /* PA8 / TIM1_CH1 */
#define PWM3_PULSE 146U /* PA7 / TIM3_CH2 */

UART_HandleTypeDef huart1;
TIM_HandleTypeDef htim1;
TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;
ADC_HandleTypeDef hadc1;

void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();

    GPIO_InitStruct.Pin = GPIO_PIN_6;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_RESET);

}

void MX_USART1_UART_Init(void)
{
    huart1.Instance = USART1;
    huart1.Init.BaudRate = 115200;
    huart1.Init.WordLength = UART_WORDLENGTH_8B;
    huart1.Init.StopBits = UART_STOPBITS_1;
    huart1.Init.Parity = UART_PARITY_NONE;
    huart1.Init.Mode = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;

    HAL_UART_Init(&huart1);
}

void MX_TIM3_Init(void)
{
    TIM_OC_InitTypeDef channel_config = {0};

    htim3.Instance = TIM3;
    htim3.Init.Prescaler = 0;
    htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim3.Init.Period = 399;
    htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_PWM_Init(&htim3);

    channel_config.OCMode = TIM_OCMODE_PWM1;
    channel_config.Pulse = PWM3_PULSE;
    channel_config.OCPolarity = TIM_OCPOLARITY_HIGH;
    channel_config.OCFastMode = TIM_OCFAST_DISABLE;
    HAL_TIM_PWM_ConfigChannel(&htim3, &channel_config, TIM_CHANNEL_2);
    channel_config.Pulse = PWM1_PULSE;
    HAL_TIM_PWM_ConfigChannel(&htim3, &channel_config, TIM_CHANNEL_3);
}

void MX_TIM1_Init(void)
{
    TIM_OC_InitTypeDef channel_config = {0};

    htim1.Instance = TIM1;
    htim1.Init.Prescaler = 0;
    htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim1.Init.Period = 399;
    htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim1.Init.RepetitionCounter = 0;
    htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_PWM_Init(&htim1);

    channel_config.OCMode = TIM_OCMODE_PWM1;
    channel_config.Pulse = PWM2_PULSE;
    channel_config.OCPolarity = TIM_OCPOLARITY_HIGH;
    channel_config.OCNPolarity = TIM_OCNPOLARITY_HIGH;
    channel_config.OCFastMode = TIM_OCFAST_DISABLE;
    channel_config.OCIdleState = TIM_OCIDLESTATE_RESET;
    channel_config.OCNIdleState = TIM_OCNIDLESTATE_RESET;
    HAL_TIM_PWM_ConfigChannel(&htim1, &channel_config, TIM_CHANNEL_1);
}

void MX_TIM2_Init(void)
{
    TIM_IC_InitTypeDef channel_config = {0};

    htim2.Instance = TIM2;
    /* The project runs from the 8 MHz HSI, so TIM2 counts in microseconds. */
    htim2.Init.Prescaler = 7;
    htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim2.Init.Period = 0xFFFFU;
    htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_IC_Init(&htim2);

    /* Count one GM event on each rising edge. */
    channel_config.ICPolarity = TIM_INPUTCHANNELPOLARITY_RISING;
    channel_config.ICSelection = TIM_ICSELECTION_DIRECTTI;
    channel_config.ICPrescaler = TIM_ICPSC_DIV1;
    channel_config.ICFilter = 0;
    HAL_TIM_IC_ConfigChannel(&htim2, &channel_config, TIM_CHANNEL_2);
    HAL_TIM_IC_ConfigChannel(&htim2, &channel_config, TIM_CHANNEL_3);
    HAL_TIM_IC_ConfigChannel(&htim2, &channel_config, TIM_CHANNEL_4);
}

void MX_ADC1_Init(void)
{
    hadc1.Instance = ADC1;
    hadc1.Init.ScanConvMode = ADC_SCAN_DISABLE;
    hadc1.Init.ContinuousConvMode = DISABLE;
    hadc1.Init.DiscontinuousConvMode = DISABLE;
    hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
    hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
    hadc1.Init.NbrOfConversion = 1;
    HAL_ADC_Init(&hadc1);
}

void HAL_UART_MspInit(UART_HandleTypeDef *huart)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    if (huart->Instance == USART1)
    {
        __HAL_RCC_USART1_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();

        GPIO_InitStruct.Pin = GPIO_PIN_9;
        GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
        GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

        GPIO_InitStruct.Pin = GPIO_PIN_10;
        GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
        GPIO_InitStruct.Pull = GPIO_NOPULL;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
    }
}

void HAL_TIM_PWM_MspInit(TIM_HandleTypeDef *htim)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    if (htim->Instance == TIM1)
    {
        __HAL_RCC_TIM1_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();

        /* PWM2: PA8 / TIM1_CH1 */
        GPIO_InitStruct.Pin = GPIO_PIN_8;
        GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
        GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
    }
    else if (htim->Instance == TIM3)
    {
        __HAL_RCC_TIM3_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();
        __HAL_RCC_GPIOB_CLK_ENABLE();

        /* PWM1: PB0 / TIM3_CH3 */
        GPIO_InitStruct.Pin = GPIO_PIN_0;
        GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
        GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
        HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

        /* PWM3: PA7 / TIM3_CH2 */
        GPIO_InitStruct.Pin = GPIO_PIN_7;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
    }
}

void HAL_TIM_IC_MspInit(TIM_HandleTypeDef *htim)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    if (htim->Instance == TIM2)
    {
        __HAL_RCC_TIM2_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();

        /* CK1: PA1/CH2, CK2: PA2/CH3, CK3: PA3/CH4 */
        GPIO_InitStruct.Pin = GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3;
        GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
        GPIO_InitStruct.Pull = GPIO_NOPULL;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

        HAL_NVIC_SetPriority(TIM2_IRQn, 1, 0);
        HAL_NVIC_EnableIRQ(TIM2_IRQn);
    }
}

void HAL_ADC_MspInit(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1)
    {
        __HAL_RCC_ADC1_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();
        __HAL_RCC_GPIOB_CLK_ENABLE();

        GPIO_InitTypeDef GPIO_InitStruct = {0};

        /* ADC1: PB1 / ADC1_IN9 */
        GPIO_InitStruct.Pin = GPIO_PIN_1;
        GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
        HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

        /* ADC2: PA4 / ADC1_IN4, ADC3: PA6 / ADC1_IN6 */
        GPIO_InitStruct.Pin = GPIO_PIN_4 | GPIO_PIN_6;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
    }
}
