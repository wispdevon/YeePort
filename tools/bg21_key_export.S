/* Offline BG21 1.4.25 diagnostic hook. Never installed by this source file.
 * Runs at the original GATT notification dispatch call, with its registers.
 * A second 07 04 + secret16 notification follows ONLY a normal 07 03 01 64
 * OTA-auth success response on attribute 0x34. Other notifications unchanged.
 */
.syntax unified
.cpu cortex-m33
.thumb
.section .text,"ax",%progbits
.global key_export_hook
.thumb_func
key_export_hook:
    push {r7, lr}
    sub sp, sp, #32
    str r0, [sp, #24]
    movs r7, #0
    ldrb.w r12, [r4, #5]
    cmp.w r12, #0x34
    bne dispatch
    ldrb.w r12, [r4, #6]
    cmp.w r12, #0
    bne dispatch
    ldrb.w r12, [r4, #7]
    cmp.w r12, #4
    bne dispatch
    ldr.w r12, [r4, #8]
    ldr r0, auth_success
    cmp r12, r0
    bne dispatch
    movs r7, #1
    ldrb r0, [r4, #4]
    str r0, [sp, #28]
dispatch:
    ldr r0, [sp, #24]
    bl vendor_dispatch
    cbz r7, finished
    movs r0, #7
    strb r0, [sp, #0]
    movs r0, #4
    strb r0, [sp, #1]
    ldr r0, factory_secret
    add r1, sp, #2
    movs r2, #16
copy_secret:
    ldrb r3, [r0], #1
    strb r3, [r1], #1
    subs r2, r2, #1
    bne copy_secret
    ldr r0, [sp, #28]
    movs r1, #0x34
    movs r2, #18
    mov r3, sp
    bl notify_original
finished:
    add sp, sp, #32
    pop {r7, lr}
    b.w original_continue
    .balign 4
auth_success:
    .word 0x64010307
factory_secret:
    .word 0x0fe0000e
