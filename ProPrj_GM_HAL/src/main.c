#include "stm32f1xx_hal.h"
#include "app_rs485.h"
#include "user.h"

#define APPLICATION_ADDRESS 0x08004000UL

void MX_GPIO_Init(void);
void MX_USART1_UART_Init(void);
void MX_TIM1_Init(void);
void MX_TIM2_Init(void);
void MX_TIM3_Init(void);
void MX_ADC1_Init(void);

int main(void)
{
    SCB->VTOR = APPLICATION_ADDRESS;
    __DSB();
    __ISB();

    HAL_Init();
    MX_GPIO_Init();
    MX_USART1_UART_Init();
    MX_TIM1_Init();
    MX_TIM2_Init();
    MX_TIM3_Init();
    MX_ADC1_Init();

    AppRs485_Init();

    User_Init();

    while (1)
    {
        User_Loop();
    }
}
