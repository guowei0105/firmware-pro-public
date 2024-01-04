#include <string.h>

#include "camera.h"
#include "i2c.h"
#include "sdram.h"
#include "common.h"
#include "display.h"
#include "mipi_lcd.h"
#include "irq.h"

#define CAMERA_CAPTURE_MODE 0 // 0: snapshot mode, 1: continuous mode

static I2C_HandleTypeDef* i2c_handle_camera = NULL;
static volatile bool capture_done = false;
static volatile bool camera_opened = false;

DCMI_HandleTypeDef DCMI_Handle;
DMA_HandleTypeDef DMA_DCMI_Handle;

static void dcmi_init()
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOG_CLK_ENABLE();
    __HAL_RCC_GPIOD_CLK_ENABLE();
    __HAL_RCC_GPIOE_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    /**DCMI GPIO Configuration
    PG10     ------> DCMI_D2
    PG9     ------> DCMI_VSYNC
    PG11     ------> DCMI_D3
    PD3     ------> DCMI_D5
    PE5     ------> DCMI_D6
    PE4     ------> DCMI_D4
    PA10     ------> DCMI_D1
    PA9     ------> DCMI_D0
    PE6     ------> DCMI_D7
    PA6     ------> DCMI_PIXCLK
    PA4     ------> DCMI_HSYNC
    */
    GPIO_InitStruct.Pin = GPIO_PIN_10 | GPIO_PIN_9 | GPIO_PIN_11;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF13_DCMI;
    HAL_GPIO_Init(GPIOG, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = GPIO_PIN_3;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF13_DCMI;
    HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = GPIO_PIN_5 | GPIO_PIN_4 | GPIO_PIN_6;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF13_DCMI;
    HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = GPIO_PIN_10 | GPIO_PIN_9 | GPIO_PIN_6 | GPIO_PIN_4;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF13_DCMI;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    __HAL_RCC_DCMI_CLK_ENABLE();
    DCMI_Handle.Instance = DCMI;
    DCMI_Handle.Init.SynchroMode = DCMI_SYNCHRO_HARDWARE;
    DCMI_Handle.Init.PCKPolarity = DCMI_PCKPOLARITY_RISING;
    DCMI_Handle.Init.VSPolarity = DCMI_VSPOLARITY_LOW;
    DCMI_Handle.Init.HSPolarity = DCMI_HSPOLARITY_LOW;
    DCMI_Handle.Init.CaptureRate = DCMI_CR_ALL_FRAME;
    DCMI_Handle.Init.ExtendedDataMode = DCMI_EXTEND_DATA_8B;
    DCMI_Handle.Init.JPEGMode = DCMI_JPEG_DISABLE;
    DCMI_Handle.Init.ByteSelectMode = DCMI_BSM_ALL;
    DCMI_Handle.Init.ByteSelectStart = DCMI_OEBS_ODD;
    DCMI_Handle.Init.LineSelectMode = DCMI_LSM_ALL;
    DCMI_Handle.Init.LineSelectStart = DCMI_OELS_ODD;

    NVIC_SetPriority(DCMI_IRQn, IRQ_PRI_DCMI);
    HAL_NVIC_EnableIRQ(DCMI_IRQn);
    HAL_DCMI_Init(&DCMI_Handle);

    __HAL_RCC_DMA2_CLK_ENABLE();
    DMA_DCMI_Handle.Instance = DMA2_Stream1;
    DMA_DCMI_Handle.Init.Request = DMA_REQUEST_DCMI;
    DMA_DCMI_Handle.Init.Direction = DMA_PERIPH_TO_MEMORY;
    DMA_DCMI_Handle.Init.PeriphInc = DMA_PINC_DISABLE;
    DMA_DCMI_Handle.Init.MemInc = DMA_MINC_ENABLE;
    DMA_DCMI_Handle.Init.PeriphDataAlignment = DMA_PDATAALIGN_WORD;
    DMA_DCMI_Handle.Init.MemDataAlignment = DMA_MDATAALIGN_WORD;
    DMA_DCMI_Handle.Init.Mode = DMA_CIRCULAR;
    DMA_DCMI_Handle.Init.Priority = DMA_PRIORITY_HIGH;
    DMA_DCMI_Handle.Init.FIFOMode = DMA_FIFOMODE_ENABLE;
    DMA_DCMI_Handle.Init.FIFOThreshold = DMA_FIFO_THRESHOLD_FULL;
    DMA_DCMI_Handle.Init.MemBurst = DMA_MBURST_SINGLE;
    DMA_DCMI_Handle.Init.PeriphBurst = DMA_PBURST_SINGLE;

    NVIC_SetPriority(DCMI_IRQn, IRQ_PRI_DCMI_DMA);
    HAL_NVIC_EnableIRQ(DMA2_Stream1_IRQn);
    HAL_DMA_Init(&DMA_DCMI_Handle);

    __HAL_LINKDMA(&DCMI_Handle, DMA_Handle, DMA_DCMI_Handle);
}

HAL_DCMI_StateTypeDef dcmi_get_state()
{
    return HAL_DCMI_GetState(&DCMI_Handle);
}

uint32_t dcmi_get_error()
{
    return HAL_DCMI_GetError(&DCMI_Handle);
}

/*
 * DMA2_Stream1_IRQHandler
 */
void DMA2_Stream1_IRQHandler(void)
{
    HAL_DMA_IRQHandler(&DMA_DCMI_Handle);
}

/*
 * DCMI_IRQHandler
 */
void DCMI_IRQHandler(void)
{
    HAL_DCMI_IRQHandler(&DCMI_Handle);
}

void HAL_DCMI_FrameEventCallback(DCMI_HandleTypeDef* hdcmi)
{
#if CAMERA_CAPTURE_MODE == 0
    camera_stop();
#else
    camera_suspend();
#endif
    capture_done = true;
}

void camera_io_init()
{
    __HAL_RCC_GPIOD_CLK_ENABLE();
    __HAL_RCC_GPIOJ_CLK_ENABLE();

    GPIO_InitTypeDef GPIO_InitStructure;

    GPIO_InitStructure.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStructure.Pull = GPIO_PULLDOWN;
    GPIO_InitStructure.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStructure.Pin = GPIO_PIN_11;
    HAL_GPIO_Init(GPIOD, &GPIO_InitStructure);
    GPIO_InitStructure.Pin = GPIO_PIN_6;
    HAL_GPIO_Init(GPIOJ, &GPIO_InitStructure);

    HAL_GPIO_WritePin(GPIOD, GPIO_PIN_11, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GPIOJ, GPIO_PIN_6, GPIO_PIN_RESET);
    HAL_Delay(10);
    HAL_GPIO_WritePin(GPIOJ, GPIO_PIN_6, GPIO_PIN_SET);
    HAL_Delay(20);
}

unsigned char camera_sccb_read_reg(unsigned char reg_addr, unsigned char* data)
{
    unsigned char ret = 0;
    if ( HAL_I2C_Mem_Read(i2c_handle_camera, GC2145_ADDR, reg_addr, I2C_MEMADD_SIZE_8BIT, data, 1, 1000) !=
         HAL_OK )
        ret = 1;
    return ret;
}

unsigned char camera_sccb_write_reg(unsigned char reg_addr, unsigned char* data)
{
    unsigned char ret = 0;
    if ( HAL_I2C_Mem_Write(i2c_handle_camera, GC2145_ADDR, reg_addr, I2C_MEMADD_SIZE_8BIT, data, 1, 1000) !=
         HAL_OK )
        ret = 1;
    return ret;
}

unsigned short camera_get_id(void)
{
    union ID
    {
        unsigned short u16;
        unsigned char u8[2];
    } myid;
    myid.u16 = 0;

    if ( camera_sccb_read_reg(0xF0, &myid.u8[1]) )
        return myid.u16;
    if ( camera_sccb_read_reg(0xF1, &myid.u8[0]) )
        return myid.u16;

    return myid.u16;
}

unsigned char camera_is_online(void)
{
    unsigned char ret = 0;
    unsigned char read = 0;

    if ( camera_sccb_read_reg(0xFB, &read) )
        return ret;

    ret = (read == GC2145_ADDR) ? 1 : 0;

    return ret;
}

void camera_start(uint8_t* buffer_address, uint32_t mode)
{
    if ( camera_opened )
    {
        camera_resume();
        return;
    }
    HAL_DCMI_Start_DMA(&DCMI_Handle, mode, (uint32_t)buffer_address, (WIN_W * WIN_H) / 2);
}

void camera_stop(void)
{
    HAL_DCMI_Stop(&DCMI_Handle);
    camera_opened = false;
}

void camera_suspend(void)
{
    HAL_DCMI_Suspend(&DCMI_Handle);
}

void camera_resume(void)
{
    HAL_DCMI_Resume(&DCMI_Handle);
}

void camera_capture_start(void)
{
#if CAMERA_CAPTURE_MODE == 0
    camera_start((uint8_t*)CAM_BUF_ADDRESS, DCMI_MODE_SNAPSHOT);
#else
    camera_start((uint8_t*)CAM_BUF_ADDRESS, DCMI_MODE_CONTINUOUS);
#endif
}

int camera_capture_done(void)
{
    int32_t tickstart = HAL_GetTick();

    while ( !capture_done )
    {
        if ( (HAL_GetTick() - tickstart) > 200 )
        {
            camera_stop();
            return 0;
        }
    }
    capture_done = false;
    return 1;
}

int camera_init(void)
{
    i2c_handle_camera = &i2c_handles[i2c_find_channel_by_device(I2C_CAMERA)];
    i2c_init_by_device(I2C_CAMERA);

    camera_get_id();

    volatile unsigned char ret = 0;
    for ( int i = 0; default_regs[i][0]; i++ )
    {
        unsigned char temp = default_regs[i][1];
        ret = camera_sccb_write_reg(default_regs[i][0], &temp);
        if ( ret )
        {
            ensure_ex(ret, 0, "camera init failed");
        }
    }

    dcmi_init();

    return ret;
}