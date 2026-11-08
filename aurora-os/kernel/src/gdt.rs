//! Global Descriptor Table (GDT) und Task State Segment (TSS).
//!
//! Im 64-Bit-Modus spielt Segmentierung kaum noch eine Rolle, aber die CPU
//! verlangt trotzdem eine GDT mit Code- und Daten-Segment. Wichtig ist das
//! TSS: Es enthält die „Interrupt Stack Table“ (IST) – saubere Ersatz-Stacks,
//! auf die die CPU bei bestimmten Exceptions automatisch wechselt.
//! So können wir selbst einen Stack-Überlauf noch abfangen.

use spin::Lazy;
use x86_64::VirtAddr;
use x86_64::instructions::segmentation::{CS, DS, ES, FS, GS, SS, Segment};
use x86_64::instructions::tables::load_tss;
use x86_64::structures::gdt::{Descriptor, GlobalDescriptorTable, SegmentSelector};
use x86_64::structures::tss::TaskStateSegment;

/// Index des Ersatz-Stacks für Double Faults in der IST
pub const DOUBLE_FAULT_IST_INDEX: u16 = 0;

const IST_STACK_SIZE: usize = 64 * 1024;

#[repr(C, align(16))]
struct Stack([u8; IST_STACK_SIZE]);

static mut DOUBLE_FAULT_STACK: Stack = Stack([0; IST_STACK_SIZE]);

static TSS: Lazy<TaskStateSegment> = Lazy::new(|| {
    let mut tss = TaskStateSegment::new();
    // Stacks wachsen nach unten -> wir tragen das obere Ende ein
    let start = VirtAddr::from_ptr(&raw const DOUBLE_FAULT_STACK);
    tss.interrupt_stack_table[DOUBLE_FAULT_IST_INDEX as usize] = start + IST_STACK_SIZE as u64;
    tss
});

struct Selectors {
    code: SegmentSelector,
    data: SegmentSelector,
    tss: SegmentSelector,
}

static GDT: Lazy<(GlobalDescriptorTable, Selectors)> = Lazy::new(|| {
    let mut gdt = GlobalDescriptorTable::new();
    let code = gdt.append(Descriptor::kernel_code_segment());
    let data = gdt.append(Descriptor::kernel_data_segment());
    let tss = gdt.append(Descriptor::tss_segment(&TSS));
    (gdt, Selectors { code, data, tss })
});

pub fn init() {
    let (gdt, sel) = &*GDT;
    gdt.load();
    unsafe {
        // Alle Segmentregister neu laden: Die alten Werte zeigen noch in
        // Limines GDT. Vor allem ein falsches SS führt sonst beim ersten
        // `iretq` (Rückkehr aus einem Interrupt) zu einer Schutzverletzung.
        CS::set_reg(sel.code);
        SS::set_reg(sel.data);
        DS::set_reg(sel.data);
        ES::set_reg(sel.data);
        FS::set_reg(sel.data);
        GS::set_reg(sel.data);
        load_tss(sel.tss);
    }
}
