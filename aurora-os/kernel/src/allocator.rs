//! Speicherverwaltung, Teil 2: der Kernel-Heap.
//!
//! Wir reservieren einen virtuellen Adressbereich, blenden dort echte
//! physische Seiten ein und übergeben ihn einem Heap-Allocator. Ab dann
//! funktionieren `Box`, `Vec`, `String`, `BTreeMap` … aus der `alloc`-Bibliothek.

use linked_list_allocator::LockedHeap;
use x86_64::VirtAddr;
use x86_64::structures::paging::{Page, PageTableFlags};

use crate::memory;

/// Weit weg von der Direct Map (0xffff_8000_…) und vom Kernel (0xffff_ffff_8…)
pub const HEAP_START: u64 = 0xffff_9000_0000_0000;
/// 64 MiB – genug für zwei bildschirmgroße Zeichenflächen (Szene + Arbeitsfläche)
/// auch in Full HD (je 8 MiB). Ab Meilenstein 6 wächst der Heap bei Bedarf.
pub const HEAP_SIZE: u64 = 64 * 1024 * 1024;

/// `#[global_allocator]` sagt Rust: Alle Heap-Anfragen gehen hierhin.
/// Später können wir das durch einen eigenen Allocator ersetzen.
#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

pub fn init() -> Result<(), &'static str> {
    let first = Page::containing_address(VirtAddr::new(HEAP_START));
    let last = Page::containing_address(VirtAddr::new(HEAP_START + HEAP_SIZE - 1));
    // beschreibbar, aber nicht ausführbar: Daten sollen nie als Code laufen
    let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::NO_EXECUTE;
    for page in Page::range_inclusive(first, last) {
        memory::map_page(page, flags)?;
    }
    unsafe { ALLOCATOR.lock().init(HEAP_START as *mut u8, HEAP_SIZE as usize) };
    Ok(())
}

/// (belegte Bytes, Gesamtgröße)
pub fn stats() -> (usize, usize) {
    let heap = ALLOCATOR.lock();
    (heap.used(), heap.size())
}
