/* Clean-room EADK runtime for the pure-Python .nwa linker (strategy C').  MIT — our own code.
 *
 * A distributed .nwa (ARM ET_REL) references `_start` (crt0) and the `eadk_*` / newlib symbols
 * but does NOT contain them: the OS-facing runtime is normally supplied by NumWorks' `nwlink`.
 * To link a .nwa WITHOUT Node and WITHOUT redistributing NumWorks' proprietary runtime, we
 * implement that runtime ourselves here, against the EADK ABI.
 *
 * The ABI is a set of FACTS (not copyrightable): each eadk_* entry is a `svc #N` with a fixed N,
 * except eadk_display_draw_string which dispatches through the OS "userland trampoline" table.
 * The svc numbers + the argument-marshalling contract were recovered empirically by linking a
 * probe app we wrote with nwlink and reading the resulting ABI (see docs/04-third-party-apps/
 * nwlink-port-plan.md, Phase 1). No nwlink source or bytes are copied; this is our transcription
 * of the observable ABI.  If NumWorks objects, this file (and the C' path) can be removed wholesale.
 *
 * Target: Cortex-M7, Thumb-2, hard-float (matches EADK device CFLAGS).
 * Symbols the linker (nwa_linker.py) must define: _data_section_start_flash,
 * _data_section_start_ram, _data_section_end_ram, _bss_section_start_ram, _bss_section_end_ram,
 * _heap_start, _heap_end, _userland_trampoline_address, and the app's `main`.
 */
    .syntax unified
    .cpu cortex-m7
    .thumb

/* ---- crt0: entered by the OS with sp set; copy .data (flash->ram), zero .bss, call main ---- */
    .section .text._start,"ax",%progbits
    .global _start
    .thumb_func
_start:
    ldr     r0, =_data_section_start_flash   /* src */
    ldr     r1, =_data_section_start_ram     /* dst */
    ldr     r2, =_data_section_end_ram       /* dst end */
0:  cmp     r1, r2
    bhs     1f
    ldrb    r3, [r0], #1
    strb    r3, [r1], #1
    b       0b
1:  ldr     r1, =_bss_section_start_ram
    ldr     r2, =_bss_section_end_ram
    movs    r3, #0
2:  cmp     r1, r2
    bhs     3f
    strb    r3, [r1], #1
    b       2b
3:  movs    r0, #0                            /* argc */
    movs    r1, #0                            /* argv */
    b       main                              /* tail-call: main's `bx lr` returns to the OS */

/* ---- eadk display: rect struct (r0:r1) spilled to the stack, then svc; scalar/ptr stays in r2 */
    .macro RECT_SVC name, num
    .section .text.\name,"ax",%progbits
    .global \name
    .thumb_func
\name:
    sub     sp, #8
    add     r3, sp, #8
    stmdb   r3, {r0, r1}
    svc     #\num
    add     sp, #8
    bx      lr
    .endm
    RECT_SVC eadk_display_pull_rect,          0x12
    RECT_SVC eadk_display_push_rect,          0x13
    RECT_SVC eadk_display_push_rect_uniform,  0x14

/* ---- eadk simple svc returning a small scalar (bool/half/word) ---- */
    .macro SVC_RET name, num, ext
    .section .text.\name,"ax",%progbits
    .global \name
    .thumb_func
\name:
    push    {r4, lr}
    svc     #\num
    mov     r4, r0
    .ifnc \ext, none
    \ext    r0, r4
    .endif
    pop     {r4, pc}
    .endm
    SVC_RET eadk_display_wait_for_vblank, 0x15, uxtb
    SVC_RET eadk_event_get,               0x17, uxth
    SVC_RET eadk_random,                  0x2d, none

/* ---- eadk void svc (no return) ---- */
    .macro SVC_VOID name, num
    .section .text.\name,"ax",%progbits
    .global \name
    .thumb_func
\name:
    svc     #\num
    bx      lr
    .endm
    SVC_VOID eadk_timing_msleep, 0x31
    SVC_VOID eadk_timing_usleep, 0x32

/* ---- eadk 64-bit return (r0:r1) via a stack scratch pair ---- */
    .macro SVC_U64 name, num
    .section .text.\name,"ax",%progbits
    .global \name
    .thumb_func
\name:
    movs    r2, #0
    movs    r3, #0
    push    {r0, r1, r4, lr}
    mov     r4, sp
    strd    r2, r3, [sp]
    svc     #\num
    str     r0, [r4]
    str     r1, [r4, #4]
    ldrd    r0, r1, [r4]
    add     sp, #8
    pop     {r4, pc}
    .endm
    SVC_U64 eadk_keyboard_scan, 0x22
    SVC_U64 eadk_timing_millis, 0x30

/* ---- eadk_display_draw_string: dispatch via the OS userland trampoline table ----
 * fn = *(*(&_dsptr)) where _dsptr holds _userland_trampoline_address; args are re-marshalled
 * to the OS layout (bg from caller stack, point repositioned) then tail-called. */
    .section .rodata.eadk_display_draw_string,"a",%progbits
    .align  2
_dsptr:
    .word   _userland_trampoline_address
    .section .text.eadk_display_draw_string,"ax",%progbits
    .global eadk_display_draw_string
    .thumb_func
eadk_display_draw_string:
    push    {r0, r1, r4, r5}
    ldr     r4, =_dsptr
    ldrh.w  r5, [sp, #0x10]
    ldr     r4, [r4]
    str     r5, [sp, #0x10]
    ldr     r4, [r4]
    str     r1, [sp, #4]
    mov     ip, r4
    add     sp, #8
    pop     {r4, r5}
    bx      ip

/* ---- newlib syscall stubs: minimal, no OS backing (games rarely use libc I/O) ---- */
    .macro RET_CONST name, val
    .section .text.\name,"ax",%progbits
    .global \name
    .thumb_func
\name:
    movs    r0, #\val
    bx      lr
    .endm
    RET_CONST _read,   0        /* EOF */
    RET_CONST _close, -1
    RET_CONST _fstat,  0
    RET_CONST _isatty, 1
    RET_CONST _lseek,  0

    .section .text._write,"ax",%progbits
    .global _write
    .thumb_func
_write:                          /* pretend the whole buffer was written (return count) */
    mov     r0, r2
    bx      lr

/* _sbrk: bump the break between _heap_start and _heap_end; -1 on exhaustion (no errno). */
    .section .data._sbrk_brk,"aw",%progbits
    .align  2
_sbrk_brk:
    .word   _heap_start
    .section .text._sbrk,"ax",%progbits
    .global _sbrk
    .thumb_func
_sbrk:                           /* r0 = increment */
    ldr     r1, =_sbrk_brk
    ldr     r2, [r1]             /* current break */
    add     r3, r2, r0           /* new break */
    ldr     r0, =_heap_end
    cmp     r3, r0
    bhi     4f                   /* over the heap end -> fail */
    str     r3, [r1]
    mov     r0, r2               /* return old break */
    bx      lr
4:  movs    r0, #0
    subs    r0, #1               /* r0 = -1 */
    bx      lr
