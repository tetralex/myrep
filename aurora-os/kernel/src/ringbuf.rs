//! Ringpuffer ohne Sperren für genau einen Schreiber (Interrupt-Handler)
//! und einen Leser (Hauptschleife).
//!
//! Warum kein `Mutex<VecDeque>`? Wenn die Hauptschleife die Sperre hält und
//! genau dann ein Interrupt kommt, wartet der Handler ewig auf die Sperre –
//! Deadlock. Außerdem darf ein Interrupt-Handler nie den Heap benutzen
//! (der Heap hat selbst eine Sperre). Dieser Puffer braucht beides nicht.

use core::cell::UnsafeCell;
use core::sync::atomic::{AtomicUsize, Ordering};

pub struct RingBuffer<const N: usize> {
    buf: UnsafeCell<[u8; N]>,
    head: AtomicUsize, // nächste Schreibposition (nur der Schreiber ändert sie)
    tail: AtomicUsize, // nächste Leseposition (nur der Leser ändert sie)
}

unsafe impl<const N: usize> Sync for RingBuffer<N> {}

impl<const N: usize> RingBuffer<N> {
    pub const fn new() -> Self {
        RingBuffer { buf: UnsafeCell::new([0; N]), head: AtomicUsize::new(0), tail: AtomicUsize::new(0) }
    }

    /// Nur aus dem Interrupt-Handler aufrufen. `false` = Puffer voll, Byte verworfen.
    pub fn push(&self, v: u8) -> bool {
        let head = self.head.load(Ordering::Relaxed);
        let tail = self.tail.load(Ordering::Acquire);
        if head.wrapping_sub(tail) == N {
            return false;
        }
        unsafe { (*self.buf.get())[head % N] = v };
        // Release: das Byte ist geschrieben, *bevor* der Leser den neuen head sieht
        self.head.store(head.wrapping_add(1), Ordering::Release);
        true
    }

    /// Nur aus der Hauptschleife aufrufen.
    pub fn pop(&self) -> Option<u8> {
        let tail = self.tail.load(Ordering::Relaxed);
        let head = self.head.load(Ordering::Acquire);
        if tail == head {
            return None;
        }
        let v = unsafe { (*self.buf.get())[tail % N] };
        self.tail.store(tail.wrapping_add(1), Ordering::Release);
        Some(v)
    }
}
