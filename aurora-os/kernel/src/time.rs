//! Zeit: Timer-Ticks seit dem Start und die Uhrzeit.

use core::sync::atomic::{AtomicI64, AtomicU64, Ordering};

/// Timer-Frequenz: 1000 Interrupts pro Sekunde = 1 Tick pro Millisekunde
pub const HZ: u64 = 1000;

/// Wird vom Timer-Interrupt hochgezählt
pub static TICKS: AtomicU64 = AtomicU64::new(0);

/// Unix-Zeit (Sekunden seit 1.1.1970, UTC) beim Start – liefert Limine aus der Hardware-Uhr
static BOOT_UNIX: AtomicI64 = AtomicI64::new(0);

/// Zeitzone: MEZ = UTC+1. Die Sommerzeit-Umstellung (MESZ) bauen wir später ein.
pub const UTC_OFFSET_SECS: i64 = 3600;

pub fn init(boot_unix: i64) {
    BOOT_UNIX.store(boot_unix, Ordering::Relaxed);
}

pub fn ticks() -> u64 {
    TICKS.load(Ordering::Relaxed)
}

/// Schlafen, bis `ms` Millisekunden vergangen sind. `hlt` hält die CPU an,
/// bis der nächste Interrupt kommt – spart Strom statt leer zu kreisen.
pub fn sleep_ms(ms: u64) {
    let end = ticks() + ms * HZ / 1000;
    while ticks() < end {
        x86_64::instructions::interrupts::enable_and_hlt();
    }
}

pub struct DateTime {
    pub year: i64,
    pub month: u32,
    pub day: u32,
    pub weekday: u32, // 0 = Sonntag
    pub hour: u32,
    pub minute: u32,
    pub second: u32,
}

pub const WEEKDAYS: [&str; 7] = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];
pub const MONTHS: [&str; 12] = [
    "Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember",
];

/// Aktuelle lokale Uhrzeit = Startzeit + vergangene Ticks + Zeitzone
pub fn now() -> DateTime {
    let secs = BOOT_UNIX.load(Ordering::Relaxed) + (ticks() / HZ) as i64 + UTC_OFFSET_SECS;
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    DateTime {
        year,
        month,
        day,
        weekday: (days + 4).rem_euclid(7) as u32, // 1.1.1970 war ein Donnerstag
        hour: (rem / 3600) as u32,
        minute: (rem / 60 % 60) as u32,
        second: (rem % 60) as u32,
    }
}

/// Tage seit 1.1.1970 -> (Jahr, Monat, Tag). Algorithmus von Howard Hinnant.
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let year = yoe + era * 400 + if month <= 2 { 1 } else { 0 };
    (year, month, day)
}
