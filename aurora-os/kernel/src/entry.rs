//! Allererster Code nach Limine – in Assembler, weil hier noch kein
//! SSE-Befehl laufen darf. Der Rust-Compiler dürfte in `kmain` sonst schon
//! SSE-Register benutzen (z. B. zum schnellen Nullsetzen von Speicher),
//! und die CPU würde mit „Invalid Opcode“ abbrechen.
//!
//! CR0.EM = 0  -> keine FPU-Emulation
//! CR0.MP = 1  -> FPU-Zustand wird bei Task-Wechsel überwacht
//! CR4.OSFXSR = 1, CR4.OSXMMEXCPT = 1 -> SSE und SSE-Exceptions erlaubt

core::arch::global_asm!(
    ".global _start",
    "_start:",
    "    mov rax, cr0",
    "    and rax, ~(1 << 2)",
    "    or  rax, 1 << 1",
    "    mov cr0, rax",
    "    mov rax, cr4",
    "    or  rax, (1 << 9) | (1 << 10)",
    "    mov cr4, rax",
    "    jmp kmain",
);
