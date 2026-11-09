//! Interrupt Descriptor Table (IDT) und Exception-Handler.
//!
//! Die IDT ist eine Tabelle mit 256 Einträgen. Tritt eine Exception auf
//! (z. B. Zugriff auf nicht gemappten Speicher), schaut die CPU in der IDT
//! nach, welche Funktion sie aufrufen soll. Fehlt der Eintrag, wird daraus
//! ein Double Fault – und fehlt auch dieser: Triple Fault = Neustart.

use core::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use spin::Lazy;
use x86_64::registers::control::Cr2;
use x86_64::structures::idt::{InterruptDescriptorTable, InterruptStackFrame, PageFaultErrorCode};

use crate::io::inb;
use crate::ringbuf::RingBuffer;
use crate::{apic, fmt, gdt, screens, serial_println, task};

static IDT: Lazy<InterruptDescriptorTable> = Lazy::new(|| {
    let mut idt = InterruptDescriptorTable::new();
    idt.divide_error.set_handler_fn(divide_error);
    idt.breakpoint.set_handler_fn(breakpoint);
    idt.invalid_opcode.set_handler_fn(invalid_opcode);
    idt.general_protection_fault.set_handler_fn(general_protection_fault);
    idt.page_fault.set_handler_fn(page_fault);
    // Hardware-Interrupts (Vektoren ab 0x20; 0–31 sind für CPU-Exceptions reserviert)
    unsafe {
        // Timer und „yield“ springen in unseren Assembler-Stub: der kann den
        // Thread wechseln (siehe task.rs)
        idt[apic::TIMER_VECTOR].set_handler_addr(task::timer_stub_addr());
        idt[task::YIELD_VECTOR].set_handler_addr(task::yield_stub_addr());
    }
    idt[apic::KEYBOARD_VECTOR].set_handler_fn(keyboard);
    idt[apic::MOUSE_VECTOR].set_handler_fn(mouse);
    idt[apic::SPURIOUS_VECTOR].set_handler_fn(spurious);
    unsafe {
        // Double Fault läuft auf eigenem Stack (IST), damit er auch bei
        // kaputtem Stack noch funktioniert.
        idt.double_fault.set_handler_fn(double_fault).set_stack_index(gdt::DOUBLE_FAULT_IST_INDEX);
    }
    idt
});

/// Wie oft ein Breakpoint (`int3`) abgefangen wurde – für den Selbsttest
pub static BREAKPOINTS: AtomicUsize = AtomicUsize::new(0);

pub fn init() {
    IDT.load();
}

/// Anzahl der Exceptions bzw. Hardware-Interrupts mit eigenem Handler
pub const HANDLER_COUNT: usize = 6;
pub const IRQ_COUNT: usize = 4;

// Rohdaten von Tastatur und Maus – die Handler legen nur Bytes ab,
// ausgewertet wird später in der Hauptschleife.
pub static KEYBOARD_BYTES: RingBuffer<256> = RingBuffer::new();
pub static MOUSE_BYTES: RingBuffer<512> = RingBuffer::new();
pub static KEYBOARD_IRQS: AtomicU64 = AtomicU64::new(0);
pub static MOUSE_IRQS: AtomicU64 = AtomicU64::new(0);

// ---------------------------------------------------------------------------
// Handler. `extern "x86-interrupt"` sorgt dafür, dass der Compiler alle
// Register sichert und mit `iretq` statt `ret` zurückkehrt.
// ---------------------------------------------------------------------------

/// Breakpoint ist harmlos: kurz loggen und einfach weitermachen.
extern "x86-interrupt" fn breakpoint(frame: InterruptStackFrame) {
    BREAKPOINTS.fetch_add(1, Ordering::Relaxed);
    serial_println!("[aurora] Breakpoint bei {:#x} – weiter geht's", frame.instruction_pointer.as_u64());
}

// --- Hardware-Interrupts: so kurz wie möglich! ------------------------------
// Während ein Handler läuft, sind weitere Interrupts gesperrt. Deshalb:
// kein Zeichnen, kein Heap, keine Sperren – nur Daten abholen und EOI senden.


extern "x86-interrupt" fn keyboard(_frame: InterruptStackFrame) {
    let byte = unsafe { inb(0x60) };
    KEYBOARD_BYTES.push(byte);
    KEYBOARD_IRQS.fetch_add(1, Ordering::Relaxed);
    apic::eoi();
}

extern "x86-interrupt" fn mouse(_frame: InterruptStackFrame) {
    let byte = unsafe { inb(0x60) };
    MOUSE_BYTES.push(byte);
    MOUSE_IRQS.fetch_add(1, Ordering::Relaxed);
    apic::eoi();
}

/// „Geister-Interrupt“ des APIC: laut Spezifikation *kein* EOI senden
extern "x86-interrupt" fn spurious(_frame: InterruptStackFrame) {}

extern "x86-interrupt" fn divide_error(frame: InterruptStackFrame) {
    fatal("Division durch Null", "Eine Ganzzahl wurde durch 0 geteilt (#DE).", &frame, None, &[]);
}

extern "x86-interrupt" fn invalid_opcode(frame: InterruptStackFrame) {
    fatal("Ungültiger Befehl", "Die CPU kennt diesen Maschinenbefehl nicht (#UD).", &frame, None, &[]);
}

extern "x86-interrupt" fn general_protection_fault(frame: InterruptStackFrame, code: u64) {
    fatal(
        "Allgemeine Schutzverletzung",
        "Unerlaubter Zugriff, z. B. auf eine nicht-kanonische Adresse (#GP).",
        &frame,
        Some(code),
        &[],
    );
}

extern "x86-interrupt" fn page_fault(frame: InterruptStackFrame, code: PageFaultErrorCode) {
    // CR2 enthält die Adresse, deren Zugriff fehlgeschlagen ist
    let addr = Cr2::read_raw();
    let access = if code.contains(PageFaultErrorCode::INSTRUCTION_FETCH) {
        "Code ausführen"
    } else if code.contains(PageFaultErrorCode::CAUSED_BY_WRITE) {
        "Schreiben"
    } else {
        "Lesen"
    };
    let reason = if code.contains(PageFaultErrorCode::PROTECTION_VIOLATION) {
        "Zugriffsrechte verletzt"
    } else {
        "Seite nicht vorhanden"
    };
    let addr_s = fmt!("{:#018x}", addr);
    let kind_s = fmt!("{} · {}", access, reason);
    let mut owner = crate::fmtbuf::LineBuf::new();
    if task::guard_page_owner(addr, &mut owner) {
        let cause = fmt!("Stack-Überlauf in Thread „{}“", owner.as_str());
        fatal(
            "Stack-Überlauf",
            "Ein Thread hat seinen Stack überschritten und die Guard-Page getroffen.",
            &frame,
            Some(code.bits()),
            &[("Ursache", cause.as_str()), ("Adresse (CR2)", addr_s.as_str())],
        );
    }
    let desc = if code.contains(PageFaultErrorCode::PROTECTION_VIOLATION) {
        "Die Seite existiert, erlaubt diesen Zugriff aber nicht (#PF)."
    } else {
        "Zugriff auf eine Speicheradresse, die nicht gemappt ist (#PF)."
    };
    fatal(
        "Page Fault",
        desc,
        &frame,
        Some(code.bits()),
        &[("Adresse (CR2)", addr_s.as_str()), ("Zugriff", kind_s.as_str())],
    );
}

extern "x86-interrupt" fn double_fault(frame: InterruptStackFrame, code: u64) -> ! {
    // Häufigste Ursache bei Threads: Stack voll -> Guard-Page -> der Page
    // Fault kann nicht einmal mehr abgelegt werden -> Double Fault
    let cr2 = Cr2::read_raw();
    let mut owner = crate::fmtbuf::LineBuf::new();
    if task::guard_page_owner(cr2, &mut owner) {
        let cause = fmt!("Stack-Überlauf in Thread „{}“", owner.as_str());
        let addr_s = fmt!("{:#018x}", cr2);
        fatal(
            "Stack-Überlauf (Double Fault)",
            "Ein Thread hat seinen Stack überschritten und die Guard-Page getroffen.",
            &frame,
            Some(code),
            &[("Ursache", cause.as_str()), ("Adresse (CR2)", addr_s.as_str())],
        );
    }
    fatal(
        "Double Fault",
        "Beim Behandeln einer Exception trat eine weitere auf (#DF).",
        &frame,
        Some(code),
        &[("Hinweis", "oft ein kaputter oder übergelaufener Stack")],
    );
}

/// Nicht behebbarer Fehler: Details auf COM1 und auf den Bildschirm, dann anhalten.
fn fatal(name: &str, desc: &str, frame: &InterruptStackFrame, code: Option<u64>, extra: &[(&str, &str)]) -> ! {
    serial_println!("\n[aurora] EXCEPTION: {}\n{:#?}", name, frame);
    if let Some(code) = code {
        serial_println!("Fehlercode: {:#x}", code);
    }
    for (k, v) in extra {
        serial_println!("{}: {}", k, v);
    }

    let rip = fmt!("{:#018x}", frame.instruction_pointer.as_u64());
    let rsp = fmt!("{:#018x}", frame.stack_pointer.as_u64());
    let flags = fmt!("{:#x}", frame.cpu_flags.bits());
    let cs = fmt!("{:#x}", frame.code_segment.0);
    let code_s = match code {
        Some(c) => fmt!("{:#x}", c),
        None => fmt!("–"),
    };

    let mut rows: [(&str, &str); 8] = [("", ""); 8];
    let mut n = 0;
    for &row in extra {
        if n < 3 {
            rows[n] = row;
            n += 1;
        }
    }
    for row in [
        ("RIP", rip.as_str()),
        ("RSP", rsp.as_str()),
        ("RFLAGS", flags.as_str()),
        ("CS", cs.as_str()),
        ("Fehlercode", code_s.as_str()),
    ] {
        rows[n] = row;
        n += 1;
    }

    screens::error_screen(name, desc, &rows[..n]);
    crate::hcf();
}
