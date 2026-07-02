MEMORY {
    zp (rw)          : ORIGIN = 0x0020,   LENGTH = 0x00E0
    ram (rw)         : ORIGIN = 0x0200,   LENGTH = 0x1E00
    bank_7e_ram (rw) : ORIGIN = 0x7E2000, LENGTH = 0xE000
    rom (rx)         : ORIGIN = 0x008000, LENGTH = 0x8000
}

__stack = 0x0200;
