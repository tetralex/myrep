//! Multitasking: Kernel-Threads mit präemptivem Scheduler.
//!
//! **Präemptiv** heißt: Der Timer-Interrupt unterbricht den laufenden Thread
//! (1000-mal pro Sekunde) und der Scheduler entscheidet, ob ein anderer
//! dran ist. Ein Thread mit Endlosschleife kann das System also nicht
//! blockieren – er bekommt einfach nur seinen Anteil an Rechenzeit.
//!
//! **Kontextwechsel**: Der gesamte Zustand eines Threads (alle Register,
//! SSE-Register, Rücksprungadresse) liegt auf *seinem eigenen Stack*. Um zu
//! wechseln, merkt sich der Scheduler den Stackpointer des alten Threads und
//! lädt den des neuen – fertig.
//!
//! Stack-Aufbau beim Wechsel (von oben nach unten):
//!   [SS, RSP, RFLAGS, CS, RIP]   <- legt die CPU beim Interrupt ab
//!   [rax … r15]                  <- 15 Register, sichert unser Assembler-Stub
//!   [512 Byte FXSAVE]            <- FPU/SSE-Zustand
//!                                <- hier zeigt der gespeicherte RSP hin

use alloc::boxed::Box;
use alloc::string::String;
use alloc::vec::Vec;
use core::sync::atomic::{AtomicBool, AtomicU64, Ordering};

use spin::Mutex;
use spin::relax::RelaxStrategy;
use x86_64::VirtAddr;
use x86_64::instructions::interrupts::without_interrupts;
use x86_64::structures::paging::{Page, PageTableFlags};

use crate::{apic, gdt, memory, time};

pub const YIELD_VECTOR: u8 = 0x81;
const SLICE_MS: u64 = 10; // Zeitscheibe

// Thread-Stacks liegen in einem eigenen Adressbereich, jeder mit einer
// nicht gemappten „Guard-Page“ darunter: Läuft ein Stack über, gibt es
// sofort einen Page Fault statt still fremden Speicher zu überschreiben.
const STACK_REGION: u64 = 0xffff_a800_0000_0000;
const STACK_PAGES: u64 = 16; // 64 KiB
const SLOT_SIZE: u64 = (STACK_PAGES + 1) * memory::PAGE_SIZE;
const MAX_SLOTS: usize = 64;

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum Prio {
    Idle = 0,
    Normal = 1,
    High = 2,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum State {
    Running,
    Ready,
    Sleeping(u64), // bis zu diesem Tick
    Blocked,       // wartet auf `unpark`
    Dead,
}

struct Task {
    id: u64,
    name: String,
    prio: Prio,
    state: State,
    rsp: u64,
    slot: Option<usize>, // Stack-Platz (None = der Start-Stack von Limine)
    ticks: u64,          // verbrauchte Rechenzeit in ms
    wake_pending: bool,
    killable: bool,
}

/// Für die Anzeige (Prozesse-App)
#[derive(Clone)]
pub struct TaskInfo {
    pub id: u64,
    pub name: String,
    pub prio: Prio,
    pub state: State,
    pub ticks: u64,
    pub killable: bool,
}

static TASKS: Mutex<Vec<Task>> = Mutex::new(Vec::new());
static SLOTS: Mutex<u64> = Mutex::new(0); // Bitmaske belegter Stack-Plätze
static CURRENT: AtomicU64 = AtomicU64::new(0);
static NEXT_ID: AtomicU64 = AtomicU64::new(1);
static ACTIVE: AtomicBool = AtomicBool::new(false);
static SLICE_START: AtomicU64 = AtomicU64::new(0);
pub static SWITCHES: AtomicU64 = AtomicU64::new(0);

// ---------------------------------------------------------------------------
// Assembler: Einsprung für Timer-Interrupt und freiwilliges Abgeben (yield)
// ---------------------------------------------------------------------------

macro_rules! switch_stub {
    ($name:literal, $handler:path) => {
        core::arch::global_asm!(
            concat!(".global ", $name),
            concat!($name, ":"),
            "    push rax", "    push rbx", "    push rcx", "    push rdx",
            "    push rsi", "    push rdi", "    push rbp",
            "    push r8",  "    push r9",  "    push r10", "    push r11",
            "    push r12", "    push r13", "    push r14", "    push r15",
            "    sub rsp, 512",
            "    fxsave64 [rsp]",      // SSE-Zustand sichern (RSP ist hier 16-Byte-ausgerichtet)
            "    mov rdi, rsp",        // 1. Argument: Stackpointer des alten Threads
            "    cld",
            "    call {handler}",      // liefert Stackpointer des neuen Threads
            "    mov rsp, rax",
            "    fxrstor64 [rsp]",
            "    add rsp, 512",
            "    pop r15", "    pop r14", "    pop r13", "    pop r12",
            "    pop r11", "    pop r10", "    pop r9",  "    pop r8",
            "    pop rbp", "    pop rdi", "    pop rsi",
            "    pop rdx", "    pop rcx", "    pop rbx", "    pop rax",
            "    iretq",
            handler = sym $handler,
        );
    };
}

switch_stub!("aurora_timer_stub", timer_entry);
switch_stub!("aurora_yield_stub", yield_entry);

unsafe extern "C" {
    fn aurora_timer_stub();
    fn aurora_yield_stub();
}

pub fn timer_stub_addr() -> VirtAddr {
    VirtAddr::new(aurora_timer_stub as *const () as u64)
}

pub fn yield_stub_addr() -> VirtAddr {
    VirtAddr::new(aurora_yield_stub as *const () as u64)
}

extern "C" fn timer_entry(rsp: u64) -> u64 {
    time::TICKS.fetch_add(1, Ordering::Relaxed);
    apic::eoi();
    schedule(rsp, true)
}

extern "C" fn yield_entry(rsp: u64) -> u64 {
    schedule(rsp, false)
}

/// Der Scheduler. Läuft im Interrupt (Interrupts gesperrt) – darf also
/// weder den Heap benutzen noch auf Sperren warten.
fn schedule(rsp: u64, from_timer: bool) -> u64 {
    if !ACTIVE.load(Ordering::Relaxed) {
        return rsp;
    }
    // Threads greifen auf TASKS nur mit gesperrten Interrupts zu – die Sperre
    // ist hier also immer frei. `try_lock` nur zur Sicherheit.
    let Some(mut tasks) = TASKS.try_lock() else { return rsp };
    let now = time::ticks();
    let cur_id = CURRENT.load(Ordering::Relaxed);
    let Some(cur) = tasks.iter().position(|t| t.id == cur_id) else { return rsp };
    tasks[cur].rsp = rsp;
    if from_timer {
        tasks[cur].ticks += 1;
    }

    // Schlafende Threads wecken
    let mut woke_higher = false;
    let cur_prio = tasks[cur].prio;
    for t in tasks.iter_mut() {
        if let State::Sleeping(until) = t.state {
            if now >= until {
                t.state = State::Ready;
                woke_higher |= t.prio > cur_prio;
            }
        }
    }

    let still_running = tasks[cur].state == State::Running;
    let slice_over = now - SLICE_START.load(Ordering::Relaxed) >= SLICE_MS;
    if from_timer && still_running && !slice_over && !woke_higher {
        return rsp; // weiterlaufen lassen
    }
    if still_running {
        tasks[cur].state = State::Ready;
    }

    // Nächsten Thread wählen: höchste Priorität, darunter reihum
    let best = tasks.iter().filter(|t| t.state == State::Ready).map(|t| t.prio).max();
    let Some(best) = best else {
        tasks[cur].state = State::Running;
        return rsp;
    };
    let n = tasks.len();
    let next = (1..=n).map(|k| (cur + k) % n).find(|&i| tasks[i].state == State::Ready && tasks[i].prio == best).unwrap_or(cur);
    tasks[next].state = State::Running;
    CURRENT.store(tasks[next].id, Ordering::Relaxed);
    SLICE_START.store(now, Ordering::Relaxed);
    if next != cur {
        SWITCHES.fetch_add(1, Ordering::Relaxed);
    }
    tasks[next].rsp
}

// ---------------------------------------------------------------------------
// Öffentliche Schnittstelle
// ---------------------------------------------------------------------------

/// Den bisher laufenden Code (kmain) zum ersten Thread machen und den
/// Leerlauf-Thread anlegen. Ab hier wird geschaltet.
pub fn init(name: &str) {
    without_interrupts(|| {
        let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
        TASKS.lock().push(Task {
            id,
            name: name.into(),
            prio: Prio::High,
            state: State::Running,
            rsp: 0,
            slot: None,
            ticks: 0,
            wake_pending: false,
            killable: false,
        });
        CURRENT.store(id, Ordering::Relaxed);
    });
    spawn_with("Leerlauf", Prio::Idle, false, || loop {
        x86_64::instructions::interrupts::enable_and_hlt();
    });
    ACTIVE.store(true, Ordering::Relaxed);
}

pub fn active() -> bool {
    ACTIVE.load(Ordering::Relaxed)
}

pub fn current_id() -> u64 {
    CURRENT.load(Ordering::Relaxed)
}

/// Neuen Thread starten (beendbar über `kill`)
pub fn spawn(name: impl Into<String>, prio: Prio, f: impl FnOnce() + Send + 'static) -> Option<u64> {
    spawn_with(name, prio, true, f)
}

pub fn spawn_system(name: impl Into<String>, prio: Prio, f: impl FnOnce() + Send + 'static) -> Option<u64> {
    spawn_with(name, prio, false, f)
}

fn spawn_with(name: impl Into<String>, prio: Prio, killable: bool, f: impl FnOnce() + Send + 'static) -> Option<u64> {
    // 1. freien Stack-Platz finden und seine Seiten einblenden (Guard-Page bleibt leer)
    let slot = without_interrupts(|| {
        let mut slots = SLOTS.lock();
        let s = (0..MAX_SLOTS).find(|&i| *slots & (1 << i) == 0)?;
        *slots |= 1 << s;
        Some(s)
    })?;
    let base = STACK_REGION + slot as u64 * SLOT_SIZE;
    let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::NO_EXECUTE;
    for p in 1..=STACK_PAGES {
        let page = Page::containing_address(VirtAddr::new(base + p * memory::PAGE_SIZE));
        without_interrupts(|| memory::map_page(page, flags)).ok()?;
    }
    let top = base + SLOT_SIZE; // oberes Ende, 16-Byte-ausgerichtet

    // 2. Anfangszustand so auf den Stack legen, als wäre der Thread gerade
    //    unterbrochen worden. Der erste Wechsel „kehrt“ dann in `trampoline` zurück.
    let closure: Box<Box<dyn FnOnce() + Send>> = Box::new(Box::new(f));
    let arg = Box::into_raw(closure) as u64;
    let (code_sel, data_sel) = gdt::selectors();
    let frame = top - 40;
    let gprs = frame - 15 * 8;
    let fx = gprs - 512;
    unsafe {
        let w = |addr: u64, v: u64| (addr as *mut u64).write(v);
        w(frame, trampoline as *const () as u64); // RIP
        w(frame + 8, code_sel as u64); // CS
        w(frame + 16, 0x202); // RFLAGS: Interrupts an
        w(frame + 24, top - 8); // RSP: wie nach einem `call` ausgerichtet
        w(frame + 32, data_sel as u64); // SS
        for i in 0..15 {
            w(gprs + i * 8, 0);
        }
        w(gprs + 9 * 8, arg); // rdi = 1. Argument für trampoline
        core::ptr::write_bytes(fx as *mut u8, 0, 512);
        (fx as *mut u16).write(0x037F); // FPU-Steuerwort: Standard
        ((fx + 24) as *mut u32).write(0x1F80); // MXCSR: alle SSE-Ausnahmen maskiert
    }

    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    let task = Task {
        id,
        name: name.into(),
        prio,
        state: State::Ready,
        rsp: fx,
        slot: Some(slot),
        ticks: 0,
        wake_pending: false,
        killable,
    };
    without_interrupts(|| TASKS.lock().push(task));
    Some(id)
}

extern "C" fn trampoline(arg: u64) -> ! {
    let f = unsafe { Box::from_raw(arg as *mut Box<dyn FnOnce() + Send>) };
    f();
    exit();
}

/// Rechenzeit freiwillig abgeben
pub fn yield_now() {
    if active() {
        unsafe { core::arch::asm!("int 0x81") };
    }
}

fn set_state(id: u64, s: State) {
    without_interrupts(|| {
        if let Some(t) = TASKS.lock().iter_mut().find(|t| t.id == id) {
            t.state = s;
        }
    });
}

pub fn sleep_until(tick: u64) {
    if !active() {
        while time::ticks() < tick {
            x86_64::instructions::interrupts::enable_and_hlt();
        }
        return;
    }
    if time::ticks() < tick {
        set_state(current_id(), State::Sleeping(tick));
        yield_now();
    }
}

pub fn sleep_ms(ms: u64) {
    sleep_until(time::ticks() + ms);
}

/// Schlafen, bis jemand `unpark` ruft (kommt `unpark` vorher, kehrt es sofort zurück)
pub fn park() {
    let id = current_id();
    let blocked = without_interrupts(|| {
        let mut tasks = TASKS.lock();
        let t = tasks.iter_mut().find(|t| t.id == id)?;
        if t.wake_pending {
            t.wake_pending = false;
            return Some(false);
        }
        t.state = State::Blocked;
        Some(true)
    });
    if blocked == Some(true) {
        yield_now();
    }
}

pub fn unpark(id: u64) {
    without_interrupts(|| {
        if let Some(t) = TASKS.lock().iter_mut().find(|t| t.id == id) {
            match t.state {
                State::Blocked => t.state = State::Ready,
                State::Dead => {}
                _ => t.wake_pending = true,
            }
        }
    });
}

/// Aktuellen Thread beenden
pub fn exit() -> ! {
    set_state(current_id(), State::Dead);
    loop {
        yield_now();
    }
}

/// Einen anderen Thread beenden. Nur für Threads gedacht, die keine Sperren
/// halten (z. B. Rechen-Threads) – sonst bliebe die Sperre für immer zu.
pub fn kill(id: u64) -> bool {
    if id == current_id() {
        return false;
    }
    without_interrupts(|| match TASKS.lock().iter_mut().find(|t| t.id == id && t.killable) {
        Some(t) => {
            t.state = State::Dead;
            true
        }
        None => false,
    })
}

/// Beendete Threads aufräumen: Stack-Seiten freigeben. Läuft in einem
/// normalen Thread (nicht im Interrupt), weil dabei Speicher freigegeben wird.
pub fn reap() -> usize {
    let dead: Vec<Task> = without_interrupts(|| {
        let mut tasks = TASKS.lock();
        let cur = current_id();
        let (dead, alive): (Vec<Task>, Vec<Task>) = tasks.drain(..).partition(|t| t.state == State::Dead && t.id != cur);
        *tasks = alive;
        dead
    });
    for t in &dead {
        if let Some(slot) = t.slot {
            let base = STACK_REGION + slot as u64 * SLOT_SIZE;
            for p in 1..=STACK_PAGES {
                let page = Page::containing_address(VirtAddr::new(base + p * memory::PAGE_SIZE));
                let _ = without_interrupts(|| memory::unmap_page(page));
            }
            without_interrupts(|| *SLOTS.lock() &= !(1 << slot));
        }
    }
    dead.len()
}

pub fn snapshot() -> Vec<TaskInfo> {
    without_interrupts(|| {
        TASKS
            .lock()
            .iter()
            .filter(|t| t.state != State::Dead)
            .map(|t| TaskInfo { id: t.id, name: t.name.clone(), prio: t.prio, state: t.state, ticks: t.ticks, killable: t.killable })
            .collect()
    })
}

/// Liegt `addr` in der Guard-Page eines Thread-Stacks? Dann Name des Threads.
/// Für Fehler-Handler: wartet nie auf die Sperre und braucht keinen Heap.
pub fn guard_page_owner(addr: u64, out: &mut crate::fmtbuf::LineBuf) -> bool {
    if addr < STACK_REGION || addr >= STACK_REGION + MAX_SLOTS as u64 * SLOT_SIZE {
        return false;
    }
    if (addr - STACK_REGION) % SLOT_SIZE >= memory::PAGE_SIZE {
        return false;
    }
    let slot = ((addr - STACK_REGION) / SLOT_SIZE) as usize;
    use core::fmt::Write;
    match TASKS.try_lock() {
        Some(tasks) => match tasks.iter().find(|t| t.slot == Some(slot)) {
            Some(t) => {
                let _ = write!(out, "{}", t.name);
            }
            None => {
                let _ = write!(out, "Stack-Platz {}", slot);
            }
        },
        None => {
            let _ = write!(out, "Stack-Platz {}", slot);
        }
    }
    true
}

/// Wartestrategie für Sperren, die von mehreren Threads benutzt werden:
/// Statt die ganze Zeitscheibe sinnlos zu kreiseln, gleich den nächsten
/// Thread rechnen lassen – vielleicht ist es genau der, der die Sperre hält.
pub struct YieldRelax;

impl RelaxStrategy for YieldRelax {
    fn relax() {
        if active() && x86_64::instructions::interrupts::are_enabled() {
            yield_now();
        } else {
            core::hint::spin_loop();
        }
    }
}

/// Sperre mit `YieldRelax` – für Daten, die sich Threads teilen
pub type ThreadMutex<T> = spin::mutex::Mutex<T, YieldRelax>;

/// Prüfen, ob die Guard-Page unter einem Stack wirklich leer ist (Selbsttest)
pub fn guard_pages_ok() -> bool {
    (0..2).all(|slot| memory::translate(VirtAddr::new(STACK_REGION + slot * SLOT_SIZE)).is_none())
}
