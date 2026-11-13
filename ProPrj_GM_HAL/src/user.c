#include "user.h"

#include "app_rs485.h"
#include "stm32f1xx_hal.h"
#include <stdio.h>

#define ADC_SAMPLE_COUNT 16U
#define J305_DOSE_WINDOW_MS 1000U
/* J305 nominal conversion: 1 CPM = 0.00812037 uSv/h. */
#define J305_NSVH_NUMERATOR 487222ULL
#define CAPTURE_INPUT_COUNT 3U

extern UART_HandleTypeDef huart1;
extern TIM_HandleTypeDef htim1;
extern TIM_HandleTypeDef htim2;
extern TIM_HandleTypeDef htim3;
extern ADC_HandleTypeDef hadc1;

typedef struct
{
    volatile uint32_t pulse_count;
    volatile uint32_t rising_edge_count;
    volatile uint32_t falling_edge_count;
    volatile uint32_t high_width_us;
    volatile uint32_t low_width_us;
    volatile uint16_t last_capture;
    volatile uint16_t last_rising_capture;
    volatile uint16_t last_falling_capture;
    volatile uint8_t rising_capture_valid;
    volatile uint8_t falling_capture_valid;
} PulseCaptureState;

static PulseCaptureState capture_state[CAPTURE_INPUT_COUNT];
static const uint16_t capture_gpio_pin[CAPTURE_INPUT_COUNT] = {
    GPIO_PIN_1, GPIO_PIN_2, GPIO_PIN_3};
static const uint32_t capture_tim_channel[CAPTURE_INPUT_COUNT] = {
    TIM_CHANNEL_2, TIM_CHANNEL_3, TIM_CHANNEL_4};
static const char *capture_name[CAPTURE_INPUT_COUNT] = {
    "CK1 PA1", "CK2 PA2", "CK3 PA3"};

static uint32_t previous_pulse_count[CAPTURE_INPUT_COUNT];
static uint32_t dose_window_start_ms;
static uint32_t dose_window_start_count[CAPTURE_INPUT_COUNT];
static uint32_t dose_rate_nsv_per_hour[CAPTURE_INPUT_COUNT];
static uint32_t dose_cps_x100[CAPTURE_INPUT_COUNT];
static uint32_t dose_cpm_x100[CAPTURE_INPUT_COUNT];
static uint8_t dose_rate_valid;

int _write(int file, char *data, int length)
{
    (void)file;
    HAL_UART_Transmit(&huart1, (uint8_t *)data, length, HAL_MAX_DELAY);
    return length;
}

void SysTick_Handler(void)
{
    HAL_IncTick();
}

void TIM2_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&htim2);
}

static void ProcessCapturedEdge(uint32_t index)
{
    PulseCaptureState *state = &capture_state[index];
    uint16_t capture = (uint16_t)HAL_TIM_ReadCapturedValue(
        &htim2, capture_tim_channel[index]);

    state->last_capture = capture;
    state->last_rising_capture = capture;
    state->rising_capture_valid = 1U;
    state->pulse_count++;
    state->rising_edge_count++;
}

void HAL_TIM_IC_CaptureCallback(TIM_HandleTypeDef *htim)
{
    if (htim->Instance != TIM2)
    {
        return;
    }

    if (htim->Channel == HAL_TIM_ACTIVE_CHANNEL_2)
    {
        ProcessCapturedEdge(0U);
    }
    else if (htim->Channel == HAL_TIM_ACTIVE_CHANNEL_3)
    {
        ProcessCapturedEdge(1U);
    }
    else if (htim->Channel == HAL_TIM_ACTIVE_CHANNEL_4)
    {
        ProcessCapturedEdge(2U);
    }
}

static HAL_StatusTypeDef ReadAdcAverage(uint32_t channel, uint32_t *adc_value)
{
    ADC_ChannelConfTypeDef channel_config = {0};
    uint32_t adc_sum = 0;
    uint32_t valid_samples = 0;

    channel_config.Channel = channel;
    channel_config.Rank = ADC_REGULAR_RANK_1;
    channel_config.SamplingTime = ADC_SAMPLETIME_239CYCLES_5;
    if (HAL_ADC_ConfigChannel(&hadc1, &channel_config) != HAL_OK)
    {
        return HAL_ERROR;
    }

    for (uint32_t i = 0; i < ADC_SAMPLE_COUNT; i++)
    {
        if (HAL_ADC_Start(&hadc1) != HAL_OK)
        {
            continue;
        }

        if (HAL_ADC_PollForConversion(&hadc1, 100) == HAL_OK)
        {
            adc_sum += HAL_ADC_GetValue(&hadc1);
            valid_samples++;
        }
        HAL_ADC_Stop(&hadc1);
    }

    if (valid_samples == 0U)
    {
        return HAL_TIMEOUT;
    }

    *adc_value = adc_sum / valid_samples;
    return HAL_OK;
}

static uint32_t AdcToOutputMillivolts(uint32_t adc_value)
{
    return (uint32_t)(
        (uint64_t)adc_value * 3300ULL * 17121ULL / (4096ULL * 100ULL));
}

static HAL_StatusTypeDef PrintAdcValue(
    const char *name,
    const char *pin,
    uint32_t channel,
    uint32_t *output_millivolts)
{
    uint32_t adc_value = 0;

    if (ReadAdcAverage(channel, &adc_value) == HAL_OK)
    {
        *output_millivolts = AdcToOutputMillivolts(adc_value);
        printf("%s %s: %lu, Vout: %lu.%03lu V\r\n",
               name,
               pin,
               adc_value,
               *output_millivolts / 1000U,
               *output_millivolts % 1000U);
        return HAL_OK;
    }

    *output_millivolts = 0U;
    printf("%s %s: read error\r\n", name, pin);
    return HAL_ERROR;
}

static void UpdateDoseRates(
    const uint32_t current_pulse_count[CAPTURE_INPUT_COUNT],
    uint32_t current_ms)
{
    uint32_t dose_elapsed_ms = current_ms - dose_window_start_ms;

    if (dose_elapsed_ms < J305_DOSE_WINDOW_MS)
    {
        return;
    }

    for (uint32_t i = 0; i < CAPTURE_INPUT_COUNT; i++)
    {
        uint32_t dose_window_pulses =
            current_pulse_count[i] - dose_window_start_count[i];

        dose_cps_x100[i] = (uint32_t)(
            (uint64_t)dose_window_pulses * 100000ULL / dose_elapsed_ms);
        dose_cpm_x100[i] = (uint32_t)(
            (uint64_t)dose_window_pulses * 6000000ULL / dose_elapsed_ms);
        dose_rate_nsv_per_hour[i] = (uint32_t)(
            (uint64_t)dose_window_pulses * J305_NSVH_NUMERATOR /
            dose_elapsed_ms);
        dose_window_start_count[i] = current_pulse_count[i];
    }

    dose_window_start_ms = current_ms;
    dose_rate_valid = 1U;
}

static void PrintCaptureValue(uint32_t index, uint32_t current_pulse_count)
{
    printf("%s: %lu pulses, %lu.%02lu CPS, Total: %lu\r\n",
           capture_name[index],
           current_pulse_count - previous_pulse_count[index],
           dose_cps_x100[index] / 100U,
           dose_cps_x100[index] % 100U,
           current_pulse_count);
    previous_pulse_count[index] = current_pulse_count;

    printf("%s signal: %s, Edges R/F: %lu/%lu, Capture: %u\r\n",
           capture_name[index],
           HAL_GPIO_ReadPin(GPIOA, capture_gpio_pin[index]) == GPIO_PIN_SET
               ? "HIGH"
               : "LOW",
           capture_state[index].rising_edge_count,
           capture_state[index].falling_edge_count,
           capture_state[index].last_capture);
    printf("%s widths: High=%lu us, Low=%lu us\r\n",
           capture_name[index],
           capture_state[index].high_width_us,
           capture_state[index].low_width_us);

    if (dose_rate_valid != 0U)
    {
        printf("%s J305: %lu.%02lu CPM, Dose: %lu.%03lu uSv/h\r\n",
               capture_name[index],
               dose_cpm_x100[index] / 100U,
               dose_cpm_x100[index] % 100U,
               dose_rate_nsv_per_hour[index] / 1000U,
               dose_rate_nsv_per_hour[index] % 1000U);
    }
    else
    {
        printf("%s J305: calculating (1 s window)\r\n",
               capture_name[index]);
    }
}

void User_Init(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);

    HAL_ADCEx_Calibration_Start(&hadc1);
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_3); /* PWM1: PB0 */
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1); /* PWM2: PA8 */
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_2); /* PWM3: PA7 */
    HAL_TIM_IC_Start_IT(&htim2, TIM_CHANNEL_2); /* CK1: PA1 */
    HAL_TIM_IC_Start_IT(&htim2, TIM_CHANNEL_3); /* CK2: PA2 */
    HAL_TIM_IC_Start_IT(&htim2, TIM_CHANNEL_4); /* CK3: PA3 */

    dose_window_start_ms = HAL_GetTick();
}

void User_Loop(void)
{
    uint32_t current_pulse_count[CAPTURE_INPUT_COUNT];
    uint32_t adc_millivolts[3];

    HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_6);

    PrintAdcValue("ADC1", "PB1", ADC_CHANNEL_9, &adc_millivolts[0]);
    PrintAdcValue("ADC2", "PA4", ADC_CHANNEL_4, &adc_millivolts[1]);
    PrintAdcValue("ADC3", "PA6", ADC_CHANNEL_6, &adc_millivolts[2]);

    for (uint32_t i = 0; i < CAPTURE_INPUT_COUNT; i++)
    {
        current_pulse_count[i] = capture_state[i].pulse_count;
    }

    uint32_t sample_timestamp_ms = HAL_GetTick();
    UpdateDoseRates(current_pulse_count, sample_timestamp_ms);

    for (uint32_t i = 0; i < CAPTURE_INPUT_COUNT; i++)
    {
        PrintCaptureValue(i, current_pulse_count[i]);
    }
    printf("------------------\r\n");

    AppRs485_SendMeasurements(
        sample_timestamp_ms, dose_cps_x100, adc_millivolts);

    HAL_Delay(1000U);
}
