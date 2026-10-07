/* Our own toy functions (MIT), used to check a camelot gcc-2.96 install.
   Not game code: they just trigger two documented Camelot codegen fingerprints. */
extern void Notify(int);

/* Fingerprint 1 (-fcall-used-r4): r4 is scratch, so the saved registers start at r5. */
int keep(int a, int b) { Notify(a); Notify(b); return a + b; }

/* Fingerprint 5: multiply by a small non-power-of-two becomes shifts and adds, no MUL. */
int scale(int x) { return x * 10; }
