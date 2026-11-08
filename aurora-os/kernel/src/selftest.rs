//! Selbsttests, die beim Start laufen und auf dem Bildschirm erscheinen.

use alloc::boxed::Box;
use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::hint::black_box;
use x86_64::VirtAddr;
use x86_64::structures::paging::{Page, PageTableFlags};

use crate::memory;

pub struct SelfTest {
    pub label: String,
    pub ok: bool,
}

fn test(label: impl Into<String>, ok: bool) -> SelfTest {
    let label = label.into();
    crate::serial_println!("[test] {} {}", if ok { "OK  " } else { "FAIL" }, label);
    SelfTest { label, ok }
}

/// Frame-Allocator: ein freigegebener Frame muss wiederverwendet werden.
pub fn frames() -> SelfTest {
    let mut guard = memory::FRAMES.lock();
    let Some(fa) = guard.as_mut() else { return test("Frame-Allocator", false) };
    let ok = match fa.alloc() {
        Some(a) => {
            fa.free(a);
            fa.alloc().inspect(|&b| fa.free(b)) == Some(a)
        }
        None => false,
    };
    test("Frame-Allocator: Frame freigeben und wiederverwenden", ok)
}

/// Paging: eine neue Seite einblenden, beschreiben und über die Direct Map
/// (eine *zweite* virtuelle Adresse für denselben physischen Frame) zurücklesen.
pub fn paging() -> SelfTest {
    let virt = VirtAddr::new(0xffff_a000_0000_0000);
    let page = Page::containing_address(virt);
    let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::NO_EXECUTE;
    let ok = (|| {
        memory::map_page(page, flags).ok()?;
        let ptr = virt.as_mut_ptr::<u64>();
        unsafe { ptr.write_volatile(0xA0A0_C0DE_F00D_CAFE) };
        let phys = memory::translate(virt)?;
        let alias = memory::phys_to_virt(phys).as_ptr::<u64>();
        let same = unsafe { alias.read_volatile() } == 0xA0A0_C0DE_F00D_CAFE;
        crate::serial_println!("[test] {:#x} -> phys {:#x} -> alias {:p}", virt.as_u64(), phys.as_u64(), alias);
        memory::unmap_page(page).ok()?;
        // nach dem Ausblenden darf es keine Übersetzung mehr geben
        Some(same && memory::translate(virt).is_none())
    })()
    .unwrap_or(false);
    test("Paging: Seite mappen, schreiben, über Direct Map lesen", ok)
}

/// Heap: Box, Vec, String und Wiederverwendung von freigegebenem Speicher.
pub fn heap() -> [SelfTest; 3] {
    let b = black_box(Box::new(41));
    let box_ok = *b + 1 == 42;

    let v: Vec<u64> = (1..=100_000).collect();
    let vec_ok = v.iter().sum::<u64>() == 5_000_050_000;
    drop(v);

    let s = format!("Hallo {} aus dem Heap", "AuroraOS");

    // black_box hindert den Optimierer daran, die Allokationen wegzulassen
    // (LLVM darf ungenutzte Box-Allokationen komplett entfernen!)
    let first = black_box(Box::new([0u8; 1024]));
    let addr = &*first as *const _ as usize;
    drop(first);
    let second = black_box(Box::new([1u8; 1024]));
    let reuse_ok = &*second as *const _ as usize == addr;
    crate::serial_println!("[test] 1. Block {:#x}, 2. Block {:p}", addr, &*second);

    [
        test("Heap: Box und Vec mit 100 000 Zahlen", box_ok && vec_ok),
        test(format!("Heap: String \"{}\"", s), s == "Hallo AuroraOS aus dem Heap"),
        test("Heap: freigegebener Speicher wird wiederverwendet", reuse_ok),
    ]
}
