//! Rechen-Threads für den Lasttest: suchen endlos Primzahlen.
//! Sie laufen mit normaler Priorität – die Oberfläche (hohe Priorität)
//! bleibt flüssig, die Rechner bekommen die übrige Rechenzeit.

use core::sync::atomic::{AtomicU64, Ordering};

use crate::task::{self, Prio};

pub static PRIMES_FOUND: AtomicU64 = AtomicU64::new(0);
pub static LARGEST_PRIME: AtomicU64 = AtomicU64::new(0);
static NEXT_START: AtomicU64 = AtomicU64::new(1_000_001);
static WORKER_NO: AtomicU64 = AtomicU64::new(1);

fn is_prime(n: u64) -> bool {
    if n < 2 || n % 2 == 0 {
        return n == 2;
    }
    let mut d = 3;
    while d * d <= n {
        if n % d == 0 {
            return false;
        }
        d += 2;
    }
    true
}

pub fn start_worker() -> Option<u64> {
    let no = WORKER_NO.fetch_add(1, Ordering::Relaxed);
    // jeder Rechner bekommt seinen eigenen Zahlenbereich
    let mut n = NEXT_START.fetch_add(1_000_000_000, Ordering::Relaxed);
    task::spawn(alloc::format!("Rechenlast {}", no), Prio::Normal, move || loop {
        // Endlosschleife ohne yield/sleep: nur der Timer kann sie unterbrechen
        if is_prime(n) {
            PRIMES_FOUND.fetch_add(1, Ordering::Relaxed);
            LARGEST_PRIME.fetch_max(n, Ordering::Relaxed);
        }
        n += 2;
    })
}

/// Absturz-Test: Rekursion ohne Ende, bis der Stack in die Guard-Page läuft
pub fn start_stack_overflow() {
    #[allow(unconditional_recursion)] // genau das ist der Sinn des Tests
    fn recurse(depth: u64) -> u64 {
        let buf = core::hint::black_box([depth; 32]);
        recurse(depth + 1) + buf[0]
    }
    task::spawn("Stack-Test", Prio::High, || {
        core::hint::black_box(recurse(0));
    });
}
