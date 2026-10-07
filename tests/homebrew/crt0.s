@ Minimal GBA homebrew startup (MIT, written for this repo).
@ Logo area is left zeroed: fine for emulators/testing; run gbafix for hardware.
	.section .text.start, "ax"
	.arm
	.global _start
_start:
	b	reset
	.fill	156, 1, 0          @ Nintendo logo (not included)
	.ascii	"GBADTDEMO\0\0\0"   @ title (12)
	.ascii	"ZDMO"              @ game code
	.ascii	"00"                @ maker
	.byte	0x96, 0, 0
	.fill	7, 1, 0
	.byte	0, 0                @ version, complement (fixed later)
	.2byte	0
reset:
	mov	r0, #0x12
	msr	cpsr_c, r0
	ldr	sp, =0x03007FA0
	mov	r0, #0x1F
	msr	cpsr_c, r0
	ldr	sp, =0x03007F00
	ldr	r0, =main
	bx	r0
	.pool
