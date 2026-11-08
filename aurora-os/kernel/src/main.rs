//! AuroraOS – Meilenstein 4: Timer, Tastatur und Maus.

#![no_std]
#![no_main]
// Erlaubt `extern "x86-interrupt" fn` – deshalb brauchen wir Rust nightly
#![feature(abi_x86_interrupt)]

// `alloc` = der Teil der Standardbibliothek, der nur einen Heap braucht
extern crate alloc;

mod acpi;
mod allocator;
mod apic;
mod desktop;
mod entry;
mod fmtbuf;
mod framebuffer;
mod gdt;
mod gfx;
mod interrupts;
mod io;
mod memory;
mod ps2;
mod ringbuf;
mod screens;
mod selftest;
mod serial;
mod time;

use core::panic::PanicInfo;
use core::sync::atomic::Ordering;

use alloc::boxed::Box;
use alloc::format;
use alloc::vec;
use alloc::vec::Vec;
use limine::request::{
    BootloaderInfoRequest, DateAtBootRequest, ExecutableCmdlineRequest, FramebufferRequest, HhdmRequest, MemmapRequest,
    RsdpRequest,
};
use limine::{BaseRevision, RequestsEndMarker, RequestsStartMarker};
use selftest::SelfTest;

// ---------------------------------------------------------------------------
// Limine-Requests
// ---------------------------------------------------------------------------

#[used]
#[unsafe(link_section = ".limine_requests")]
static BASE_REVISION: BaseRevision = BaseRevision::new();

#[used]
#[unsafe(link_section = ".limine_requests")]
static FRAMEBUFFER_REQUEST: FramebufferRequest = FramebufferRequest::new();

#[used]
#[unsafe(link_section = ".limine_requests")]
static BOOTLOADER_INFO_REQUEST: BootloaderInfoRequest = BootloaderInfoRequest::new();

/// Kommandozeile aus limine.conf (`cmdline: …`) – damit wählen wir Absturz-Tests
#[used]
#[unsafe(link_section = ".limine_requests")]
static CMDLINE_REQUEST: ExecutableCmdlineRequest = ExecutableCmdlineRequest::new();

/// Offset der Direct Map (physischer Speicher ab dieser virtuellen Adresse)
#[used]
#[unsafe(link_section = ".limine_requests")]
static HHDM_REQUEST: HhdmRequest = HhdmRequest::new();

/// Speicherkarte: welche physischen Bereiche frei, belegt oder reserviert sind
#[used]
#[unsafe(link_section = ".limine_requests")]
static MEMMAP_REQUEST: MemmapRequest = MemmapRequest::new();

/// Adresse der ACPI-Wurzeltabelle (RSDP)
#[used]
#[unsafe(link_section = ".limine_requests")]
static RSDP_REQUEST: RsdpRequest = RsdpRequest::new();

/// Datum und Uhrzeit beim Start (Unix-Zeit aus der Hardware-Uhr)
#[used]
#[unsafe(link_section = ".limine_requests")]
static DATE_REQUEST: DateAtBootRequest = DateAtBootRequest::new();

#[used]
#[unsafe(link_section = ".limine_requests_start")]
static _START_MARKER: RequestsStartMarker = RequestsStartMarker::new();

#[used]
#[unsafe(link_section = ".limine_requests_end")]
static _END_MARKER: RequestsEndMarker = RequestsEndMarker::new();

#[unsafe(no_mangle)]
unsafe extern "C" fn kmain() -> ! {
    serial::init();
    serial_println!("[aurora] Kernel gestartet");
    assert!(BASE_REVISION.is_supported(), "Limine unterstützt unsere Base-Revision nicht");

    // --- Framebuffer --------------------------------------------------------
    let fb = FRAMEBUFFER_REQUEST
        .response()
        .and_then(|r| r.framebuffers().first().copied())
        .expect("kein Framebuffer von Limine erhalten");
    assert!(fb.bpp == 32, "nur 32-bpp-Framebuffer werden unterstützt");
    framebuffer::init(framebuffer::FbInfo {
        addr: fb.address() as usize,
        width: fb.width,
        height: fb.height,
        pitch: fb.pitch,
        bpp: fb.bpp,
        shift: (fb.red_mask_shift, fb.green_mask_shift, fb.blue_mask_shift),
    });
    // Ab hier kann der Panic-Handler einen Fehlerbildschirm zeichnen.

    // --- CPU-Tabellen -------------------------------------------------------
    gdt::init();
    serial_println!("[aurora] GDT + TSS geladen");
    interrupts::init();
    serial_println!("[aurora] IDT geladen");

    // Selbsttest: int3 löst eine Breakpoint-Exception aus. Kommt der Kernel
    // danach hier weiter, funktionieren IDT, Handler und `iretq`.
    x86_64::instructions::interrupts::int3();
    let bp_ok = interrupts::BREAKPOINTS.load(Ordering::Relaxed) == 1;

    // --- Speicher -----------------------------------------------------------
    let hhdm = HHDM_REQUEST.response().expect("keine HHDM-Antwort").offset;
    let memmap = MEMMAP_REQUEST.response().expect("keine Speicherkarte");
    let mem = memory::init(hhdm, memmap.entries());
    serial_println!("[aurora] Direct Map ab {:#x}", hhdm);
    allocator::init().expect("Heap konnte nicht eingerichtet werden");
    serial_println!("[aurora] Heap: {} MiB ab {:#x}", allocator::HEAP_SIZE / 1024 / 1024, allocator::HEAP_START);
    // Ab hier funktionieren Box, Vec, String, format! …

    // --- Interrupt-Controller, Timer, PS/2 ----------------------------------
    time::init(DATE_REQUEST.response().map(|d| d.timestamp).unwrap_or(0));
    let rsdp = RSDP_REQUEST.response().expect("keine ACPI-Tabellen").address as u64;
    let madt = acpi::find_madt(rsdp, hhdm).expect("MADT nicht gefunden");
    let apic_info = apic::init(&madt);
    let ps2 = ps2::init();
    apic::route_isa_irq(&madt, 1, apic::KEYBOARD_VECTOR);
    apic::route_isa_irq(&madt, 12, apic::MOUSE_VECTOR);
    // Ab jetzt dürfen Hardware-Interrupts kommen
    x86_64::instructions::interrupts::enable();
    serial_println!("[aurora] Interrupts aktiv, APIC-Timer {} Ticks/ms", apic_info.timer_ticks_per_ms);

    // Timer-Test: 20 ms schlafen. Hängt der Timer, käme `sleep_ms` nie zurück –
    // deshalb zählen wir stattdessen, wie viele Ticks in 50 `hlt` vergehen.
    let t0 = time::ticks();
    for _ in 0..50 {
        x86_64::instructions::interrupts::enable_and_hlt();
    }
    let timer_ok = time::ticks() > t0 + 10;

    // --- Selbsttests --------------------------------------------------------
    let mut tests = vec![
        SelfTest { label: format!("GDT, TSS und IDT ({} Handler + {} IRQs)", interrupts::HANDLER_COUNT, interrupts::IRQ_COUNT), ok: true },
        SelfTest { label: "Breakpoint (int3) abgefangen, Kernel läuft weiter".into(), ok: bp_ok },
        selftest::frames(),
        selftest::paging(),
    ];
    tests.extend(selftest::heap());
    tests.push(SelfTest { label: format!("ACPI: MADT gefunden, {} CPU-Kern(e), I/O APIC", madt.cpus), ok: !madt.ioapics.is_empty() });
    tests.push(SelfTest { label: format!("APIC-Timer: {} Hz (geeicht mit dem PIT)", time::HZ), ok: timer_ok });
    let mouse_label = if ps2.wheel { "PS/2: Tastatur und Maus mit Scrollrad" } else { "PS/2: Tastatur und Maus" };
    tests.push(SelfTest { label: mouse_label.into(), ok: ps2.mouse });

    // --- Startbildschirm ----------------------------------------------------
    let fbi = framebuffer::info().unwrap();
    let bl = match BOOTLOADER_INFO_REQUEST.response() {
        Some(b) => format!("{} {}", b.name(), b.version()),
        None => "unbekannt".into(),
    };
    let (heap_used, heap_size) = allocator::stats();
    let report = screens::BootReport {
        info: vec![
            ("Bildschirm", format!("{} × {} · {} bpp", fbi.width, fbi.height, fbi.bpp)),
            ("Bootloader", bl),
            ("Kernel-Heap", format!("{} belegt von {}", screens::human(heap_used as u64), screens::human(heap_size as u64))),
        ],
        mem,
        tests,
    };
    screens::boot_screen(&report);
    serial_println!("[aurora] Startbildschirm gezeichnet ({} Speicherbereiche)", mem.entries);
    time::sleep_ms(2500);

    // --- Absturz-Tests (Auswahl im Limine-Menü) -----------------------------
    let cmdline = CMDLINE_REQUEST.response().map(|r| r.cmdline()).unwrap_or("");
    if let Some(test) = cmdline.split_whitespace().find_map(|a| a.strip_prefix("crash=")) {
        serial_println!("[aurora] Absturz-Test: {}", test);
        crash_test(test);
    }

    // --- Interaktiver Bildschirm -------------------------------------------
    serial_println!("[aurora] Starte Desktop – viel Spaß beim Tippen!");
    desktop::Desktop::new(&ps2).run();
}

/// Löst absichtlich verschiedene Exceptions aus.
fn crash_test(kind: &str) {
    unsafe {
        match kind {
            // Lesen von einer Adresse, die nicht gemappt ist
            "pagefault" => {
                core::ptr::read_volatile(0xdead_beef_000 as *const u64);
            }
            // Stackpointer auf ungültige Adresse setzen, dann int3:
            // Die CPU kann den Interrupt-Frame nicht ablegen -> Page Fault.
            // Auch der Page-Fault-Frame passt nicht auf diesen Stack -> Double Fault.
            // Der Double-Fault-Handler läuft auf seinem IST-Stack und rettet uns.
            "doublefault" => core::arch::asm!("mov rsp, {0}", "int3", in(reg) 0xdead_0000u64, options(noreturn)),
            // Hardware-Division durch 0 (in Rust würde das vorher eine Panic auslösen)
            "divide" => core::arch::asm!("xor edx, edx", "xor ecx, ecx", "div ecx", out("eax") _, out("ecx") _, out("edx") _),
            // ud2 ist ein absichtlich ungültiger Befehl
            "opcode" => core::arch::asm!("ud2"),
            // Nicht-kanonische Adresse (Bits 48–63 passen nicht zu Bit 47)
            "gpf" => {
                core::ptr::read_volatile(0x8000_0000_0000_0000u64 as *const u64);
            }
            "panic" => panic!("Test-Panic aus dem Limine-Menü"),
            // Mehr Speicher anfordern, als der Heap hat -> Allocation-Fehler -> Panic
            "oom" => {
                let big: Vec<u8> = vec![0; 256 * 1024 * 1024];
                serial_println!("{}", big.len());
            }
            // Code im Heap ausführen: Die Heap-Seiten sind als NO_EXECUTE markiert,
            // die CPU verweigert das mit einem Page Fault (Schutzverletzung).
            "nx" => {
                let code = Box::new([0xC3u8]); // 0xC3 = `ret`
                let f: extern "C" fn() = core::mem::transmute(&*code as *const u8);
                f();
            }
            other => serial_println!("[aurora] unbekannter Test: {}", other),
        }
    }
}

#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    serial_println!("\n[aurora] KERNEL PANIC: {}", info);
    let msg = fmt!("{}", info.message());
    let loc = match info.location() {
        Some(l) => {
            // lange Pfade (z. B. aus der Rust-Bibliothek) auf die letzten zwei Teile kürzen
            let file = l.file();
            let short = file.rmatch_indices('/').nth(1).map(|(i, _)| &file[i + 1..]).unwrap_or(file);
            fmt!("{}:{}", short, l.line())
        }
        None => fmt!("unbekannt"),
    };
    screens::error_screen(
        "Kernel Panic",
        "Der Kernel hat einen Fehler erkannt und sich selbst angehalten.",
        &[("Meldung", msg.as_str()), ("Ort", loc.as_str())],
    );
    hcf();
}

/// „Halt and catch fire“: Interrupts aus und die CPU für immer anhalten.
pub fn hcf() -> ! {
    loop {
        unsafe { core::arch::asm!("cli; hlt", options(nomem, nostack)) };
    }
}
