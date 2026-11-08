/* AuroraOS Kernel-Linker-Skript */
OUTPUT_FORMAT(elf64-x86-64)
ENTRY(_start)

/* Eigene Programm-Header, damit Limine korrekte Rechte (R/W/X) setzt */
PHDRS
{
    limine_requests PT_LOAD;
    text            PT_LOAD;
    rodata          PT_LOAD;
    data            PT_LOAD;
}

SECTIONS
{
    /* Higher-Half-Kernel: wir liegen in den obersten 2 GiB des Adressraums */
    . = 0xffffffff80000000;

    /* Limine sucht seine Requests zwischen Start- und End-Marker */
    .limine_requests : {
        KEEP(*(.limine_requests_start))
        KEEP(*(.limine_requests))
        KEEP(*(.limine_requests_end))
    } :limine_requests

    . = ALIGN(CONSTANT(MAXPAGESIZE));
    .text : { *(.text .text.*) } :text

    . = ALIGN(CONSTANT(MAXPAGESIZE));
    .rodata : { *(.rodata .rodata.*) } :rodata

    . = ALIGN(CONSTANT(MAXPAGESIZE));
    .data : { *(.data .data.*) } :data

    /* .bss muss als letzte Sektion im data-Segment stehen */
    .bss : {
        *(COMMON)
        *(.bss .bss.*)
    } :data

    /DISCARD/ : {
        *(.eh_frame*)
        *(.note .note.*)
    }
}
