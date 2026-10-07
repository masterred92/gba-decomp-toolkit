CFLAGS = -mthumb -mthumb-interwork -mcpu=arm7tdmi -O2 -ffreestanding -nostdlib
demo.gba: crt0.s main.c gba.ld
	arm-none-eabi-gcc $(CFLAGS) -T gba.ld -o demo.elf crt0.s main.c
	arm-none-eabi-objcopy -O binary demo.elf demo.gba
	python3 -c "import sys;sys.path.insert(0,'../..');from gbadt.header import fix_header as f;d=bytearray(open('demo.gba','rb').read());open('demo.gba','wb').write(f(d))"
# Same program, different layout (two extra functions) for signature tests.
demo_b.gba: crt0.s main.c gba.ld
	arm-none-eabi-gcc $(CFLAGS) -DLAYOUT_B -T gba.ld -o demo_b.elf crt0.s main.c
	arm-none-eabi-objcopy -O binary demo_b.elf demo_b.gba
	python3 -c "import sys;sys.path.insert(0,'../..');from gbadt.header import fix_header as f;d=bytearray(open('demo_b.gba','rb').read());open('demo_b.gba','wb').write(f(d))"
clean:
	rm -f demo.elf demo.gba demo_b.elf demo_b.gba
