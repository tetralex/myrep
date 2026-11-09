//! Jede App rendert in ihrem eigenen Thread.
//!
//! Fenstermanager (UI-Thread) und App-Thread tauschen sich über einen
//! „Briefkasten“ aus:
//!   UI  --Auftrag (Größe + Kopie aller Daten)-->  App
//!   UI  <--------- fertiges Bild ---------------  App
//! Der UI-Thread wartet nie auf eine App. Ist ein Bild noch nicht fertig,
//! zeigt er einfach weiter das alte – selbst eine hängende App kann den
//! Rest des Systems nicht einfrieren.

use crate::apps::{self, AppKind, Snapshot};
use crate::paint::Image;
use crate::task::{self, Prio, ThreadMutex};

struct Mailbox {
    job: Option<(i32, i32, Snapshot)>,
    result: Option<Image>,
    quit: bool,
    task: u64,
}

impl Mailbox {
    const EMPTY: Self = Mailbox { job: None, result: None, quit: false, task: 0 };
}

static BOXES: [ThreadMutex<Mailbox>; 5] = [
    ThreadMutex::new(Mailbox::EMPTY),
    ThreadMutex::new(Mailbox::EMPTY),
    ThreadMutex::new(Mailbox::EMPTY),
    ThreadMutex::new(Mailbox::EMPTY),
    ThreadMutex::new(Mailbox::EMPTY),
];

fn mailbox(app: AppKind) -> &'static ThreadMutex<Mailbox> {
    &BOXES[app as usize]
}

/// Thread für eine App starten (beim Öffnen des Fensters)
pub fn start(app: AppKind) {
    {
        let mut b = mailbox(app).lock();
        if b.task != 0 {
            return;
        }
        *b = Mailbox::EMPTY;
    }
    let name = alloc::format!("App: {}", app.title());
    if let Some(id) = task::spawn_system(name, Prio::High, move || run(app)) {
        mailbox(app).lock().task = id;
    }
}

/// Thread bitten, sich zu beenden (beim Schließen). Bewusst kein `kill`:
/// Die App könnte gerade eine Sperre halten (z. B. den Schrift-Cache) –
/// die bliebe sonst für immer gesperrt. Also: höflich fragen.
pub fn stop(app: AppKind) {
    let id = {
        let mut b = mailbox(app).lock();
        b.quit = true;
        core::mem::replace(&mut b.task, 0)
    };
    if id != 0 {
        task::unpark(id);
    }
}

/// Neuen Auftrag einwerfen (ersetzt einen noch nicht begonnenen alten)
pub fn request(app: AppKind, w: i32, h: i32, snap: Snapshot) {
    let id = {
        let mut b = mailbox(app).lock();
        b.job = Some((w, h, snap));
        b.task
    };
    if id != 0 {
        task::unpark(id);
    }
}

/// Fertiges Bild abholen, falls vorhanden
pub fn take_result(app: AppKind) -> Option<Image> {
    mailbox(app).lock().result.take()
}

fn run(app: AppKind) {
    loop {
        let (job, quit) = {
            let mut b = mailbox(app).lock();
            (b.job.take(), b.quit)
        };
        if quit {
            return; // Thread endet -> task::exit()
        }
        match job {
            Some((w, h, snap)) => {
                let mut img = Image::new(w, h);
                apps::draw(app, &mut img, &snap);
                mailbox(app).lock().result = Some(img);
            }
            None => task::park(), // schlafen bis zum nächsten Auftrag
        }
    }
}
