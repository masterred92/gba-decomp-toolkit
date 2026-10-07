/* Tiny GBA demo (MIT). Mode 3 gradient + a few functions to match. */
typedef unsigned short u16; typedef unsigned int u32;
#define REG_DISPCNT (*(volatile u32 *)0x04000000)
#define VRAM ((volatile u16 *)0x06000000)

u16 rgb15(u32 r, u32 g, u32 b) { return (u16)((r & 31) | ((g & 31) << 5) | ((b & 31) << 10)); }

u32 checksum(const unsigned char *p, u32 n) {
    u32 s = 0;
    while (n--) s = (s << 1 | s >> 31) ^ *p++;
    return s;
}

void fill_gradient(void) {
    for (u32 y = 0; y < 160; y++)
        for (u32 x = 0; x < 240; x++)
            VRAM[y * 240 + x] = rgb15(x >> 3, y >> 3, (x + y) >> 4);
}

int main(void) {
    REG_DISPCNT = 0x0403; /* mode 3, BG2 */
    fill_gradient();
    for (;;) {}
}
