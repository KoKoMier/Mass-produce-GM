ENTRY(Reset_Handler)
_estack = ORIGIN(RAM) + LENGTH(RAM);
_Min_Heap_Size = 0x200;
_Min_Stack_Size = 0x400;

MEMORY
{
  RAM   (xrw) : ORIGIN = 0x20000000, LENGTH = 20K
  FLASH (rx)  : ORIGIN = 0x08004000, LENGTH = 48K
}

INCLUDE ldscripts/common_sections.ld
